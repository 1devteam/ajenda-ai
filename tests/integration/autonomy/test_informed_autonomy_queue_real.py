"""AU-02: informed autonomy disclaimer queues task and writes audit event."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.domain.audit_event import AuditEvent
from backend.domain.execution_task import ExecutionTask
from backend.domain.tenant import Tenant
from backend.main import create_app
from backend.services.autonomy.disclaimer_catalog import disclaimer_for_action
from tests.integration.credentials.credential_e2e_support import auth_headers, provision_operational_tenant

pytestmark = pytest.mark.integration


def _upgrade_tenant_to_pro(pg_engine: object, tenant_id: str) -> None:
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = session_factory()
    try:
        tenant = session.get(Tenant, uuid.UUID(tenant_id))
        assert tenant is not None
        tenant.plan = "pro"
        session.commit()
    finally:
        session.close()


def test_tier3_autonomy_ack_queues_task_and_writes_audit_event(
    integration_env: None,
    pg_engine: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AJENDA_SIGNUP_ENABLED", "true")
    monkeypatch.setenv("AJENDA_SIGNUP_EXPOSE_VERIFICATION_TOKEN", "true")
    monkeypatch.setenv("AJENDA_EMAIL_PROVIDER", "noop")
    monkeypatch.setenv("AJENDA_AUTONOMY_DISCLAIMER_MODE", "pilot")
    from backend.app.config import get_settings

    get_settings.cache_clear()

    entry = disclaimer_for_action("gtm.crm_upsert")
    assert entry is not None

    tenant_id: str
    principal_id: str
    with TestClient(create_app()) as client:
        tenant_id, api_key = provision_operational_tenant(client, prefix="autonomy-au02")
        _upgrade_tenant_to_pro(pg_engine, tenant_id)

        me = client.get("/v1/account/me", headers=auth_headers(tenant_id=tenant_id, api_key=api_key))
        assert me.status_code == 200, me.text
        principal_id = me.json()["principal"]["subject_id"]

        create_resp = client.post(
            "/v1/account/provider-credentials",
            headers=auth_headers(tenant_id=tenant_id, api_key=api_key),
            json={
                "credential_id": "hubspot-crm",
                "provider": "external_crm",
                "integration": "hubspot",
                "secret_value": "autonomy-test-hubspot-pak",
            },
        )
        assert create_resp.status_code == 201, create_resp.text

        launch = client.post(
            "/v1/ability-runtime/tasks",
            headers={
                **auth_headers(tenant_id=tenant_id, api_key=api_key),
                "Idempotency-Key": str(uuid.uuid4()),
            },
            json={
                "action": "gtm.crm_upsert",
                "input": {
                    "record_type": "contact",
                    "data": {"email": "autonomy@example.com", "firstname": "Autonomy"},
                },
                "idempotency_key": f"au02-{uuid.uuid4().hex[:8]}",
                "credential_reference": {
                    "schema_version": 1,
                    "credential_id": "hubspot-crm",
                    "provider": "external_crm",
                    "credential_type": "api_key",
                },
                "autonomy_acknowledgment": {
                    "schema_version": 1,
                    "disclaimer_id": entry.disclaimer_id,
                    "disclaimer_text_hash": entry.text_hash,
                    "accepted_at": "2026-06-26T12:00:00+00:00",
                    "principal_id": principal_id,
                    "action": "gtm.crm_upsert",
                    "side_effect_class": "external_write",
                },
            },
        )
        assert launch.status_code == 202, launch.text
        body = launch.json()
        task_id = body["task_id"]

    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    verify_session = session_factory()
    try:
        task = verify_session.get(ExecutionTask, uuid.UUID(task_id))
        assert task is not None
        assert task.requires_human_review is False
        side_effect_auth = task.metadata_json.get("execution_constraints", {}).get("side_effect_authorization", {})
        assert side_effect_auth.get("approved_by") == f"autonomy:{principal_id}"

        audit_rows = list(
            verify_session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.action == "autonomy_disclaimer_accepted",
                )
                .order_by(AuditEvent.created_at.asc())
            )
        )
        assert len(audit_rows) == 1
        audit = audit_rows[0]
        assert audit.payload_json["task_id"] == task_id
        assert audit.payload_json["disclaimer_id"] == entry.disclaimer_id
        assert audit.payload_json["principal_id"] == principal_id
    finally:
        verify_session.close()