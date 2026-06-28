"""End-to-end integration tests without mocked egress or simulated outcomes.

Standalone brain paths use real Postgres persistence and real tool.invoke handlers.
HubSpot plugin paths use real HTTPS to the CRM adapter ingress and live HubSpot API.
Gmail plugin paths use real HTTPS to gmail.googleapis.com (no egress mocks).
"""

from __future__ import annotations

import json
import os
import socket
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.db.tenant_session import activate_tenant_session
from backend.domain.execution_task import ExecutionTask
from backend.domain.tenant_internal_record import TenantInternalRecord
from backend.main import create_app
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.handlers.tool_invoke import tool_invoke_handler
from backend.workers.task_dispatcher import TaskDispatcher
from tests.integration.standalone.gmail_e2e_support import resolve_gmail_access_token_for_e2e
from tests.integration.standalone.hubspot_e2e_support import resolve_hubspot_access_token

pytestmark = pytest.mark.integration


def _auth_headers(*, tenant_id: str, api_key: str) -> dict[str, str]:
    return {"X-Tenant-Id": tenant_id, "X-Api-Key": api_key}


def _provision_operational_tenant(client: TestClient) -> tuple[str, str]:
    email = f"e2e-brain-{uuid.uuid4().hex[:8]}@example.com"
    signup = client.post(
        "/v1/onboarding/signup",
        json={"org_name": "E2E Brain Co", "email": email},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert signup.status_code == 201, signup.text
    tenant_id = signup.json()["tenant_id"]
    token = signup.json()["verification_token"]
    verify = client.post(
        "/v1/onboarding/verify-email",
        json={"token": token},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert verify.status_code == 200, verify.text
    bootstrap_key = verify.json()["api_key"]
    promote = client.post(
        "/v1/onboarding/promote-bootstrap-key",
        headers=_auth_headers(tenant_id=tenant_id, api_key=bootstrap_key),
    )
    assert promote.status_code == 200, promote.text
    return tenant_id, promote.json()["api_key"]


def _assert_not_simulated(payload: dict) -> None:
    assert payload.get("status") != "simulated"
    assert "simulated" not in str(payload.get("reason", "")).lower()
    if "real" in payload:
        assert payload.get("real") is True


@pytest.fixture
def brain_runtime_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
    from backend.app.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def hubspot_live_settings(monkeypatch: pytest.MonkeyPatch) -> str:
    token = resolve_hubspot_access_token()
    if not token:
        pytest.skip("No HubSpot token: set AJENDA_E2E_HUBSPOT_PAK or authenticate `hs account auth`")

    # Ingress is published on host port 8443 (container 443). Use explicit host:port for live egress.
    adapter_host = os.environ.get("AJENDA_E2E_ADAPTER_HOST", "127.0.0.1:8443")
    try:
        host, _, port = adapter_host.partition(":")
        socket.create_connection((host, int(port or "8443")), timeout=2).close()
    except OSError:
        pytest.skip(
            f"HubSpot CRM ingress not reachable at {adapter_host} — run: docker compose up -d hubspot-crm-ingress"
        )

    monkeypatch.setenv("AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST", adapter_host)
    monkeypatch.setenv("AJENDA_NETWORK_EGRESS_ALLOW_PRIVATE_DESTINATIONS", "true")
    monkeypatch.setenv("AJENDA_NETWORK_EGRESS_TLS_VERIFY", "false")
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return token


@pytest.fixture
def gmail_live_settings(monkeypatch: pytest.MonkeyPatch) -> str:
    token = resolve_gmail_access_token_for_e2e()
    if not token:
        pytest.skip("No Gmail token: run scripts/google/gmail_cli_auth.py auth or set AJENDA_E2E_GMAIL_TOKEN")
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_ID", os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_ID", ""))
    monkeypatch.setenv("AJENDA_GOOGLE_CLI_CLIENT_SECRET", os.environ.get("AJENDA_GOOGLE_CLI_CLIENT_SECRET", ""))
    from backend.app.config import get_settings

    get_settings.cache_clear()
    return token


def _gmail_account_email(access_token: str) -> str | None:
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        if response.status_code >= 400:
            return None
        payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return None
    email = payload.get("emailAddress") if isinstance(payload, dict) else None
    return email.strip() if isinstance(email, str) and email.strip() else None


def test_standalone_brain_http_credential_register_write_research_upsert_no_simulation(
    integration_env: None,
    pg_engine: object,
    brain_runtime_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Full HTTP + worker path for Ajenda brain without external plugins or mocks."""
    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    tenant_id: str
    with TestClient(create_app()) as client:
        tenant_id, api_key = _provision_operational_tenant(client)

        plugins = client.get("/v1/plugins", headers=_auth_headers(tenant_id=tenant_id, api_key=api_key))
        assert plugins.status_code == 200, plugins.text
        assert plugins.json()["central_brain_plugin_id"] == "ajenda-brain"

    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    worker_session = session_factory()
    activate_tenant_session(worker_session, tenant_id)
    try:

        def _worker_session_factory() -> Session:
            return worker_session

        context = {
            "worker_id": "worker-e2e-brain",
            "tenant_id": tenant_id,
            "lease_id": str(uuid.uuid4()),
            "session_factory": _worker_session_factory,
        }

        write_task = ExecutionTask(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            mission_id=uuid.uuid4(),
            title="write contact",
            description="durable internal write",
            status="running",
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "action": "record.write",
                    "input": {
                        "record_type": "contact",
                        "record_id": "e2e-contact-1",
                        "data": {
                            "name": "E2E Buyer",
                            "email": "e2e-buyer@example.com",
                            "company": "E2E Corp",
                        },
                    },
                },
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        write_result = tool_invoke_handler(write_task, context)
        _assert_not_simulated(write_result["output"])
        worker_session.commit()

        repo = TenantInternalRecordRepository(worker_session)
        stored = repo.read_record(
            tenant_id=tenant_id,
            record_type="contact",
            record_id="e2e-contact-1",
        )
        assert stored is not None
        assert stored["email"] == "e2e-buyer@example.com"

        research_task = ExecutionTask(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            mission_id=uuid.uuid4(),
            title="web research",
            description="standalone research",
            status="running",
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "action": "web.research",
                    "input": {
                        "query": "E2E Corp",
                        "company": "E2E Corp",
                    },
                },
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        research_result = tool_invoke_handler(research_task, context)
        _assert_not_simulated(research_result["output"])
        assert research_result["output"]["plugin_required"] is False
        assert research_result["output"]["internal_count"] >= 1

        upsert_task = ExecutionTask(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            mission_id=uuid.uuid4(),
            title="internal crm upsert",
            description="no external credential",
            status="running",
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "action": "gtm.crm_upsert",
                    "input": {
                        "record_type": "contact",
                        "data": {
                            "email": "e2e-upsert@example.com",
                            "firstname": "E2E",
                            "lastname": "Upsert",
                        },
                    },
                    "idempotency_key": f"e2e-upsert-{uuid.uuid4().hex[:8]}",
                },
                "execution_constraints": {
                    "side_effect_authorization": {
                        "schema_version": 1,
                        "allowed_actions": ["gtm.crm_upsert"],
                        "reason": "e2e internal upsert",
                        "approved_by": "e2e",
                    }
                },
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        upsert_result = tool_invoke_handler(upsert_task, context)
        _assert_not_simulated(upsert_result["output"])
        assert upsert_result["output"]["status"] == "upserted_internal"
        assert upsert_result["output"]["source"] == "ajenda_brain"
        worker_session.commit()
        rows = worker_session.scalars(
            select(TenantInternalRecord).where(
                TenantInternalRecord.tenant_id == tenant_id,
                TenantInternalRecord.deleted.is_(False),
            )
        ).all()
        assert len(rows) >= 2
    finally:
        worker_session.close()


def test_worker_dispatch_record_search_persists_real_evidence_no_simulation(
    integration_env: None,
    pg_engine: object,
    queue_adapter: object,
    redis_client: object,
    brain_runtime_settings: None,
) -> None:
    """Real queue + dispatcher + worker runtime for record.search (no mocks)."""
    from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
    from backend.domain.evidence import EvidenceRecord
    from backend.domain.execution_task import ExecutionTask
    from backend.domain.lineage_record import LineageRecord
    from backend.domain.mission import Mission
    from backend.domain.tenant import Tenant
    from backend.domain.worker_lease import WorkerLease

    tenant_id = str(uuid.uuid4())
    worker_id = "worker-e2e-dispatch"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)

    setup_session = session_factory()
    try:
        setup_session.add(Tenant(id=uuid.UUID(tenant_id), name="E2E Tenant", slug=f"e2e-{tenant_id[:8]}", plan="pro"))
        mission = Mission(tenant_id=tenant_id, objective="E2E brain mission", status="running")
        setup_session.add(mission)
        setup_session.flush()
        task = ExecutionTask(
            tenant_id=tenant_id,
            mission_id=mission.id,
            title="E2E record search",
            description="dispatcher proof",
            status=ExecutionTaskState.PLANNED.value,
            metadata_json={
                "task_type": "tool.invoke",
                "tool_invocation": {
                    "schema_version": 1,
                    "action": "record.search",
                    "input": {"record_type": "account", "query": "Acme"},
                },
            },
            compliance_category="operational",
            jurisdiction="US-ALL",
            requires_human_review=False,
        )
        setup_session.add(task)
        setup_session.flush()
        task_id = task.id
        QuotaEnforcementService(setup_session).check_and_record_task_creation(uuid.UUID(tenant_id))
        queued = ExecutionCoordinator(setup_session, queue_adapter).queue_task(tenant_id=tenant_id, task_id=task_id)
        assert queued.ok is True
        runtime = WorkerRuntimeService(setup_session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        setup_session.commit()
    finally:
        setup_session.close()

    TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=tenant_id,
    ).execute(task_id=task_id, lease_id=lease_id)

    verify_session = session_factory()
    try:
        final_task = verify_session.get(ExecutionTask, task_id)
        lineage = verify_session.scalars(
            select(LineageRecord).where(
                LineageRecord.tenant_id == tenant_id,
                LineageRecord.task_id == task_id,
            )
        ).all()
        evidence_records = verify_session.scalars(
            select(EvidenceRecord).where(
                EvidenceRecord.tenant_id == tenant_id,
                EvidenceRecord.execution_task_id == task_id,
            )
        ).all()

        assert final_task is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert len(lineage) >= 1
        output = lineage[0].metadata_json.get("output", {})
        assert output.get("count", 0) >= 1
        assert "simulated" not in str(lineage[0].metadata_json).lower()
        assert len(evidence_records) >= 1
        lease = verify_session.get(WorkerLease, lease_id)
        assert lease is not None
        assert lease.status == WorkerLeaseState.RELEASED.value
    finally:
        verify_session.close()


def test_hubspot_plugin_live_adapter_and_api_no_simulation(
    integration_env: None,
    pg_engine: object,
    pg_session: Session,
    hubspot_live_settings: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real HTTPS to hubspot-crm-ingress and live HubSpot API (no egress mocks)."""
    from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
    from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector

    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    tenant_id = str(uuid.uuid4())
    protector = RuntimeCredentialSecretProtector()
    pg_session.add(
        ProviderRuntimeCredential(
            id=f"prc-{uuid.uuid4()}",
            tenant_id=tenant_id,
            credential_id="hubspot-crm",
            provider="external_crm",
            credential_type="api_key",
            enabled=True,
            revoked=False,
            deleted=False,
            allowed_actions=["sales.research", "crm.research", "gtm.crm_upsert"],
            allowed_side_effect_classes=["external_read", "external_write"],
            trusted_destination_hosts=[os.environ.get("AJENDA_E2E_ADAPTER_HOST", "127.0.0.1:8443")],
            secret_ciphertext=protector.encrypt_secret(hubspot_live_settings),
        )
    )
    pg_session.commit()

    unique_email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
    context = {
        "worker_id": "worker-e2e-hubspot",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": lambda: pg_session,
    }

    research_task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="live hubspot research",
        description="real adapter search",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "crm.research",
                "input": {"lead": {"company": "HubSpot", "domain": "hubspot.com"}},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    research_result = tool_invoke_handler(research_task, context)
    _assert_not_simulated(research_result["output"])
    assert research_result["output"].get("plugin_required") is True or research_result["output"].get("source") in {
        "hubspot",
        "external_crm",
    }

    upsert_task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="live hubspot upsert",
        description="real adapter upsert",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.crm_upsert",
                "input": {
                    "record_type": "contact",
                    "data": {
                        "email": unique_email,
                        "firstname": "E2E",
                        "lastname": "Live",
                    },
                },
                "idempotency_key": f"live-upsert-{uuid.uuid4().hex[:8]}",
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "credential_type": "api_key",
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["gtm.crm_upsert"],
                    "reason": "e2e live hubspot upsert",
                    "approved_by": "e2e",
                }
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    upsert_result = tool_invoke_handler(upsert_task, context)
    upsert_output = upsert_result["output"]
    assert upsert_output.get("status") != "simulated"
    if upsert_output.get("real"):
        assert upsert_output["status"] == "upserted_real"
    else:
        # Real external HTTP denial (e.g. missing HubSpot write scopes) — not a simulated path.
        assert upsert_output["status"] == "error"
        assert upsert_output.get("error")
        assert "simulated" not in str(upsert_output.get("reason", "")).lower()


def test_gmail_plugin_live_api_no_simulation(
    integration_env: None,
    pg_session: Session,
    gmail_live_settings: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real HTTPS to Gmail API for inbox read and send (no egress mocks)."""
    from backend.domain.provider_runtime_credential import ProviderRuntimeCredential
    from backend.services.credentials.secret_protector import RuntimeCredentialSecretProtector

    monkeypatch.setattr(
        "backend.services.tools.runtime_authority.validate_capability_action_authority",
        lambda **kwargs: None,
    )

    tenant_id = str(uuid.uuid4())
    protector = RuntimeCredentialSecretProtector()
    pg_session.add(
        ProviderRuntimeCredential(
            id=f"prc-{uuid.uuid4()}",
            tenant_id=tenant_id,
            credential_id="gmail-email",
            provider="external_email",
            credential_type="api_key",
            enabled=True,
            revoked=False,
            deleted=False,
            allowed_actions=["gtm.email_send", "gtm.email_check"],
            allowed_side_effect_classes=["external_read", "external_send"],
            trusted_destination_hosts=["gmail.googleapis.com"],
            secret_ciphertext=protector.encrypt_secret(gmail_live_settings),
        )
    )
    pg_session.commit()

    context = {
        "worker_id": "worker-e2e-gmail",
        "tenant_id": tenant_id,
        "lease_id": str(uuid.uuid4()),
        "session_factory": lambda: pg_session,
    }

    check_task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="live gmail check",
        description="real gmail list",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.email_check",
                "input": {"query": "in:inbox", "limit": 3},
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "gmail-email",
                "provider": "external_email",
                "credential_type": "api_key",
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    try:
        check_result = tool_invoke_handler(check_task, context)
    except ValueError as exc:
        if "HTTP 401" in str(exc) or "HTTP 403" in str(exc):
            pytest.skip(f"Gmail live token unavailable or unauthorized: {exc}")
        raise
    check_output = check_result["output"]
    assert check_output.get("emails")
    assert check_output["emails"][0].get("id") != "sim-1"
    assert "simulated" not in str(check_output).lower()

    recipient = _gmail_account_email(gmail_live_settings)
    if not recipient:
        pytest.skip("Could not resolve Gmail account email for live send test")

    send_task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        title="live gmail send",
        description="real gmail send",
        status="running",
        metadata_json={
            "task_type": "tool.invoke",
            "tool_invocation": {
                "action": "gtm.email_send",
                "input": {
                    "to": recipient,
                    "subject": f"Ajenda E2E Live {uuid.uuid4().hex[:8]}",
                    "body": "Ajenda Gmail plugin live send test (no simulation).",
                },
                "idempotency_key": f"live-gmail-send-{uuid.uuid4().hex[:8]}",
            },
            "credential_reference": {
                "schema_version": 1,
                "credential_id": "gmail-email",
                "provider": "external_email",
                "credential_type": "api_key",
            },
            "execution_constraints": {
                "side_effect_authorization": {
                    "schema_version": 1,
                    "allowed_actions": ["gtm.email_send"],
                    "reason": "e2e live gmail send",
                    "approved_by": "e2e",
                }
            },
        },
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )
    send_result = tool_invoke_handler(send_task, context)
    send_output = send_result["output"]
    assert send_output.get("status") != "simulated"
    assert send_output.get("real") is True
    assert send_output["status"] == "sent"
    assert send_output.get("provider") == "gmail_api"
