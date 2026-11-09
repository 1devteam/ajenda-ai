"""Opt-in, live public-research proof through Ajenda's runtime path.

The test deliberately calls a real public search endpoint.  It is therefore
excluded from ordinary CI and needs ``AJENDA_LIVE_PUBLIC_RESEARCH=1``.  It uses
real PostgreSQL and Redis for composition, admission, queueing, leasing,
dispatch, evidence persistence, and fresh-session artifact readback.

It never treats a search hit as a verified company, or a verified company as a
qualified prospect.  A completed search with no verifiable identities is a
valid, evidence-backed insufficient-information outcome.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.api.routes import mission as mission_module
from backend.api.routes import mission_composition as composition_module
from backend.api.routes import mission_deliverable as deliverable_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.db.tenant_session import activate_tenant_session
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.evidence import EvidenceRecord
from backend.domain.execution_task import ExecutionTask
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.internet.contracts import PageSnapshot
from backend.services.mission_composition.deliverable_runtime_artifacts import collect_materialized_artifacts
from backend.services.mission_composition.proposal_store import clear_proposals_for_tests
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration

_LIVE_FLAG = "AJENDA_LIVE_PUBLIC_RESEARCH"
_LIVE_BROWSER_FLAG = "AJENDA_LIVE_BROWSER_OBSERVATION"
_INSTRUCTION = (
    "Research and qualify up to three HVAC companies in Dallas using public sources only. "
    "Do not contact anyone or modify any external system."
)
_CONTROLLED_PROVIDER_FAILURE = {
    "provider": "duckduckgo_html",
    "real": False,
    "results": [],
    "error": "controlled provider timeout",
    "attempts": [
        {
            "provider": "duckduckgo_html",
            "outcome": "failure",
            "result_count": 0,
            "status_code": None,
            "error": "controlled provider timeout",
        }
    ],
}
_CONTROLLED_PROVIDER_EMPTY = {
    "provider": "controlled_governed_search",
    "real": True,
    "results": [],
    "error": None,
    "attempts": [
        {
            "provider": "controlled_governed_search",
            "outcome": "empty",
            "result_count": 0,
            "status_code": 200,
            "error": None,
        }
    ],
}
_CONTROLLED_DIRECTORY_SEARCH = {
    "provider": "controlled_governed_search",
    "real": True,
    "results": [
        {
            "title": "15 Best Commercial HVAC Contractors Dallas, TX",
            "snippet": "Find and invite the best commercial HVAC contractors in Dallas.",
            "url": "https://downtobid.com/contractors/hvac/dallas",
            "source": "controlled_public_result",
        }
    ],
    "error": None,
    "attempts": [
        {
            "provider": "controlled_governed_search",
            "outcome": "results",
            "result_count": 1,
            "status_code": 200,
            "error": None,
        }
    ],
}
_CONTROLLED_DIRECTORY_PAGE = PageSnapshot(
    url="https://downtobid.com/contractors/hvac/dallas",
    real=True,
    status_code=200,
    title="15 Best Commercial HVAC Contractors Dallas, TX",
    text_preview="Find and invite the best commercial HVAC contractors in Dallas. Access our contractor database.",
    body_preview="Browse contractors and submit bid requests.",
    extraction={"links": []},
)


def _build_app(*, tenant_id: uuid.UUID, session, queue_adapter) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="live-public-research-operator",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(composition_module.router, prefix="/v1")
    app.include_router(mission_module.router, prefix="/v1")
    app.include_router(deliverable_module.router, prefix="/v1")
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: session
    app.dependency_overrides[get_queue_adapter] = lambda: queue_adapter
    return app


def _approve_ready_pending_tasks(*, session, queue_adapter, tenant_id: str, mission_id: uuid.UUID) -> bool:
    """Approve only tasks whose final, dependency-bound payload is available."""

    tasks = list(
        session.scalars(
            select(ExecutionTask).where(
                ExecutionTask.tenant_id == tenant_id,
                ExecutionTask.mission_id == mission_id,
            )
        )
    )
    pending_reviews = [task for task in tasks if task.status == ExecutionTaskState.PENDING_REVIEW.value]
    if not pending_reviews:
        return False
    coordinator = ExecutionCoordinator(session, queue_adapter)
    changed_any = False
    for task in pending_reviews:
        try:
            approved = coordinator.approve_review_and_queue(
                tenant_id=tenant_id,
                task_id=task.id,
                actor="human:public-research-runtime-proof",
                approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        except ValueError as exc:
            if "input binding deferred" in str(exc):
                continue
            if "review approval input binding failed" not in str(exc):
                raise
            changed_any = True
            continue
        assert approved.ok is True
        changed_any = True
    if changed_any:
        session.commit()
    return changed_any


def _drain_mission(*, session, factory, queue_adapter, tenant_id: str, mission_id: uuid.UUID) -> None:
    """Execute every admitted task through the canonical queue/lease path."""

    for sequence in range(24):
        session.expire_all()
        tasks = list(
            session.scalars(
                select(ExecutionTask).where(
                    ExecutionTask.tenant_id == tenant_id,
                    ExecutionTask.mission_id == mission_id,
                )
            )
        )
        if tasks and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks):
            return
        if _approve_ready_pending_tasks(
            session=session,
            queue_adapter=queue_adapter,
            tenant_id=tenant_id,
            mission_id=mission_id,
        ):
            continue
        worker_id = f"live-public-research-{sequence}"
        runtime = WorkerRuntimeService(session, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)
        if claimed is None:
            continue
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=tenant_id, lease_id=lease_id, worker_id=worker_id)
        session.commit()
        TaskDispatcher(
            session_factory=factory,
            vector_session_factory=factory,
            queue=queue_adapter,
            worker_id=worker_id,
            tenant_id=tenant_id,
        ).execute(task_id=claimed.id, lease_id=lease_id)
    session.expire_all()
    tasks = list(
        session.scalars(
            select(ExecutionTask).where(
                ExecutionTask.tenant_id == tenant_id,
                ExecutionTask.mission_id == mission_id,
            )
        )
    )
    raise AssertionError(
        "live public-research graph did not drain: "
        + repr(
            [
                {
                    "action": task.metadata_json.get("tool_invocation", {}).get("action"),
                    "status": task.status,
                    "failure": task.metadata_json.get("failure"),
                    "dependency_deferral": task.metadata_json.get("dependency_deferral"),
                    "output": task.metadata_json.get("handler_result", {}).get("output"),
                    "binding": task.metadata_json.get("input_binding_audit"),
                }
                for task in tasks
            ]
        )
    )


@pytest.mark.live
def test_live_public_research_preserves_provider_attempts_and_evidence_outcome(
    pg_engine,
    queue_adapter,
) -> None:
    """Run the original public-research mission with no fixtures or CRM data."""

    if os.environ.get(_LIVE_FLAG) != "1":
        pytest.skip(f"set {_LIVE_FLAG}=1 to run this external read-only proof")

    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(Tenant(id=tenant_id, name="Live public research", slug=f"public-{tenant_id.hex[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()

        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed_response = client.post("/v1/missions/compose", json={"instruction": _INSTRUCTION})
            assert composed_response.status_code == 200, composed_response.text
            composed = composed_response.json()
            assert composed["ready_to_start"] is True, composed
            assert {step["action_name"] for step in composed["planned_steps"]} >= {
                "web.research",
                "research.verify_public_candidates",
                "sales.qualify",
            }
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "live-public-research-v2"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            launched = launched_response.json()
            assert launched["runtime_admitted"] is True
            # The composition may contain both an independently admissible
            # public-read root and review-held, evidence-bound dependents.
            # ``_drain_mission`` proves either path reaches the same governed
            # queue/lease/dispatcher boundary.
            assert launched["queued_task_ids"] or launched["pending_review_task_ids"]
        setup.commit()
        _drain_mission(
            session=setup,
            factory=factory,
            queue_adapter=queue_adapter,
            tenant_id=tenant_text,
            mission_id=mission_id,
        )
    finally:
        setup.close()

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_text)
        tasks = list(
            verify.scalars(
                select(ExecutionTask).where(
                    ExecutionTask.tenant_id == tenant_text,
                    ExecutionTask.mission_id == mission_id,
                )
            )
        )
        assert tasks and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks)
        leases = list(verify.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_text)))
        assert leases and all(lease.status == WorkerLeaseState.RELEASED.value for lease in leases)

        research_task = next(
            task for task in tasks if task.metadata_json["tool_invocation"]["action"] == "web.research"
        )
        verifier_task = next(
            task
            for task in tasks
            if task.metadata_json["tool_invocation"]["action"] == "research.verify_public_candidates"
        )
        qualification_task = next(
            task for task in tasks if task.metadata_json["tool_invocation"]["action"] == "sales.qualify"
        )
        research_output = research_task.metadata_json["handler_result"]["output"]
        assert research_output["exclude_internal_records"] is True
        assert research_output["source_partitions"]["tenant_internal"]["record_count"] == 0
        attempts = research_output["provider_attempts"]
        assert attempts
        assert all(isinstance(item.get("provider"), str) and item["provider"] for item in attempts)
        assert all(item.get("outcome") in {"results", "empty", "failure"} for item in attempts)

        artifacts = collect_materialized_artifacts(tasks)
        verified = next((item for item in artifacts if item.artifact_key == "verified_prospect_candidates"), None)
        qualified = next((item for item in artifacts if item.artifact_key == "qualified_prospects"), None)
        assert verified is not None
        assert qualified is not None
        assert isinstance(verified.payload, list)
        assert isinstance(qualified.payload, list)
        verifier_output = verifier_task.metadata_json["handler_result"]["output"]
        qualification_output = qualification_task.metadata_json["handler_result"]["output"]
        if not verified.payload:
            assert isinstance(verifier_output.get("research_gap"), str) and verifier_output["research_gap"].strip()
            assert verifier_output["valid_empty_result"]["classification"] == "valid_empty"
        else:
            assert all(item.get("identity_status") == "verified" for item in verified.payload)
            assert all(item.get("identity_evidence_urls") for item in verified.payload)
        if not qualified.payload:
            assert qualification_output["valid_empty_result"]["classification"] == "valid_empty"

        evidence = list(
            verify.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.tenant_id == tenant_text,
                    EvidenceRecord.mission_id == mission_id,
                    EvidenceRecord.execution_task_id.in_([task.id for task in tasks]),
                )
            )
        )
        evidence_task_ids = {item.execution_task_id for item in evidence}
        assert {task.id for task in tasks} <= evidence_task_ids
        assert any(item.evidence_source == "tool.invoke.web.research" for item in evidence)
    finally:
        verify.close()


def test_runtime_control_diagnostic_persists_through_canonical_runtime(pg_engine, queue_adapter) -> None:
    """Run Ajenda's local-only control diagnostic through queue, lease, and readback."""

    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(Tenant(id=tenant_id, name="Runtime diagnostics", slug=f"controls-{tenant_id.hex[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()
        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        instruction = (
            "Verify runtime controls for HTTPS-only egress, private-address rejection, "
            "destination policy, and retry idempotency."
        )
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed_response = client.post("/v1/missions/compose", json={"instruction": instruction})
            assert composed_response.status_code == 200, composed_response.text
            composed = composed_response.json()
            assert [step["action_name"] for step in composed["planned_steps"]] == ["runtime.verify_controls"]
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "runtime-controls-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            setup.commit()
            _drain_mission(
                session=setup,
                factory=factory,
                queue_adapter=queue_adapter,
                tenant_id=tenant_text,
                mission_id=mission_id,
            )
    finally:
        setup.close()

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_text)
        task = verify.scalar(
            select(ExecutionTask).where(
                ExecutionTask.tenant_id == tenant_text,
                ExecutionTask.mission_id == mission_id,
            )
        )
        assert task is not None
        assert task.status == ExecutionTaskState.COMPLETED.value
        output = task.metadata_json["handler_result"]["output"]["runtime_control_verification_package"]
        assert output["proof_manifest"] == {
            "redacted": True,
            "credentials_used": False,
            "external_actions_performed": False,
            "network_calls_performed": False,
            "evidence_types": ["local_fixture_probe", "source_reference"],
        }
        controls = {item["control"]: item for item in output["controls"]}
        assert {
            "network_authority",
            "https_only",
            "private_address_rejection",
            "destination_policy",
            "retry_idempotency",
        } <= set(controls)
        assert all(item["status"] == "proven" for item in controls.values())
        evidence = list(
            verify.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.tenant_id == tenant_text,
                    EvidenceRecord.execution_task_id == task.id,
                )
            )
        )
        assert evidence
        assert any(item.evidence_source == "tool.invoke.runtime.verify_controls" for item in evidence)
    finally:
        verify.close()


def test_disabled_browser_observation_fails_after_canonical_dispatch(pg_engine, queue_adapter, monkeypatch) -> None:
    """Establish where disabled browser availability becomes visible in runtime."""

    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "false")
    from backend.app import config as config_module

    if hasattr(config_module.get_settings, "cache_clear"):
        config_module.get_settings.cache_clear()

    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(Tenant(id=tenant_id, name="Disabled browser", slug=f"browser-{tenant_id.hex[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()
        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        instruction = "Observe https://www.iana.org/domains/reserved and return the page title. Do not modify anything."
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed_response = client.post("/v1/missions/compose", json={"instruction": instruction})
            assert composed_response.status_code == 200, composed_response.text
            composed = composed_response.json()
            assert composed["ready_to_start"] is True
            assert [step["action_name"] for step in composed["planned_steps"]] == ["web.browser_session"]
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "disabled-browser-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            launched = launched_response.json()
            assert launched["pending_review_task_ids"] == []
            assert launched["queued_task_ids"]
            setup.commit()

        runtime = WorkerRuntimeService(setup, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_text, worker_id="disabled-browser-worker")
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_text, lease_id=lease_id, worker_id="disabled-browser-worker")
        runtime.start_execution(tenant_id=tenant_text, lease_id=lease_id, worker_id="disabled-browser-worker")
        setup.commit()
        TaskDispatcher(
            session_factory=factory,
            vector_session_factory=factory,
            queue=queue_adapter,
            worker_id="disabled-browser-worker",
            tenant_id=tenant_text,
        ).execute(task_id=claimed.id, lease_id=lease_id)
    finally:
        setup.close()

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_text)
        task = verify.scalar(
            select(ExecutionTask).where(
                ExecutionTask.tenant_id == tenant_text,
                ExecutionTask.mission_id == mission_id,
            )
        )
        assert task is not None
        assert task.status == ExecutionTaskState.FAILED.value
        governance = task.metadata_json["ability_governance"]
        assert governance["ability_id"] == "web-browser-session"
        assert governance["approval_required"] is False
        assert "ability_authorization" not in task.metadata_json.get("execution_constraints", {})
        failure = task.metadata_json.get("failure") or {}
        assert "web page observation requirements were not satisfied" in str(failure)
        lease = verify.get(WorkerLease, lease_id)
        assert lease is not None
        assert lease.status == WorkerLeaseState.RELEASED.value
    finally:
        verify.close()


@pytest.mark.live
def test_live_browser_observation_persists_through_canonical_runtime(pg_engine, queue_adapter, monkeypatch) -> None:
    """Run the enabled browser path through composition, queue, dispatch, and durable readback."""

    if os.environ.get(_LIVE_BROWSER_FLAG) != "1":
        pytest.skip(f"set {_LIVE_BROWSER_FLAG}=1 to run this external read-only proof")

    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "true")
    from backend.app import config as config_module

    if hasattr(config_module.get_settings, "cache_clear"):
        config_module.get_settings.cache_clear()

    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(Tenant(id=tenant_id, name="Live browser", slug=f"browser-live-{tenant_id.hex[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()
        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        instruction = "Observe https://www.iana.org/domains/reserved and return the page title. Do not modify anything."
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed_response = client.post("/v1/missions/compose", json={"instruction": instruction})
            assert composed_response.status_code == 200, composed_response.text
            composed = composed_response.json()
            assert [step["action_name"] for step in composed["planned_steps"]] == ["web.browser_session"]
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "live-browser-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            launched = launched_response.json()
            assert launched["pending_review_task_ids"]
            task_id = uuid.UUID(launched["pending_review_task_ids"][0])
            approved = ExecutionCoordinator(setup, queue_adapter).approve_review_and_queue(
                tenant_id=tenant_text,
                task_id=task_id,
                actor="human:browser-proof-reviewer",
                approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            assert approved.ok is True
            setup.commit()

        runtime = WorkerRuntimeService(setup, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=tenant_text, worker_id="live-browser-worker")
        assert claimed is not None
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=tenant_text, lease_id=lease_id, worker_id="live-browser-worker")
        runtime.start_execution(tenant_id=tenant_text, lease_id=lease_id, worker_id="live-browser-worker")
        setup.commit()
        TaskDispatcher(
            session_factory=factory,
            vector_session_factory=factory,
            queue=queue_adapter,
            worker_id="live-browser-worker",
            tenant_id=tenant_text,
        ).execute(task_id=claimed.id, lease_id=lease_id)
    finally:
        setup.close()
        if hasattr(config_module.get_settings, "cache_clear"):
            config_module.get_settings.cache_clear()

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_text)
        task = verify.scalar(
            select(ExecutionTask).where(
                ExecutionTask.tenant_id == tenant_text,
                ExecutionTask.mission_id == mission_id,
            )
        )
        assert task is not None
        assert task.status == ExecutionTaskState.COMPLETED.value
        output = task.metadata_json["handler_result"]["output"]
        observation = output["web_page_observation"]
        assert observation["title"] == "IANA-managed Reserved Domains"
        assert observation["observation_satisfied"] is True
        assert observation["network_provenance"] == {
            "request_vetting": "network_egress_per_request",
            "dns_pin": "chromium_host_resolver_rules",
            "dns_pinned_hosts": ["www.iana.org"],
            "allowed_hosts": ["www.iana.org"],
            "engine": "playwright_chromium",
            "ephemeral_context": True,
        }
        lease = verify.get(WorkerLease, lease_id)
        assert lease is not None
        assert lease.status == WorkerLeaseState.RELEASED.value
        evidence = list(
            verify.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.tenant_id == tenant_text,
                    EvidenceRecord.execution_task_id == task.id,
                )
            )
        )
        assert any(item.evidence_source == "tool.invoke.web.browser_session" for item in evidence)
    finally:
        verify.close()


def test_provider_failure_remains_distinct_from_valid_empty_research(pg_engine, queue_adapter) -> None:
    """A failed provider cannot complete the verifier/qualification as empty evidence."""

    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(Tenant(id=tenant_id, name="Provider failure", slug=f"provider-{tenant_id.hex[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()

        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
            patch(
                "backend.services.tools.standalone_actions._fetch_governed_public_search",
                return_value=_CONTROLLED_PROVIDER_FAILURE,
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed_response = client.post("/v1/missions/compose", json={"instruction": _INSTRUCTION})
            assert composed_response.status_code == 200, composed_response.text
            composed = composed_response.json()
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "provider-failure-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
        setup.commit()

        for sequence in range(12):
            _approve_ready_pending_tasks(
                session=setup,
                queue_adapter=queue_adapter,
                tenant_id=tenant_text,
                mission_id=mission_id,
            )
            setup.expire_all()
            tasks = list(
                setup.scalars(
                    select(ExecutionTask).where(
                        ExecutionTask.tenant_id == tenant_text,
                        ExecutionTask.mission_id == mission_id,
                    )
                )
            )
            verifier = next(
                (
                    task
                    for task in tasks
                    if task.metadata_json["tool_invocation"]["action"] == "research.verify_public_candidates"
                ),
                None,
            )
            if verifier is not None and verifier.status == ExecutionTaskState.FAILED.value:
                break
            runtime = WorkerRuntimeService(setup, queue_adapter)
            claimed = runtime.claim_next_task(tenant_id=tenant_text, worker_id=f"provider-failure-{sequence}")
            if claimed is None:
                continue
            lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
            runtime.heartbeat(tenant_id=tenant_text, lease_id=lease_id, worker_id=f"provider-failure-{sequence}")
            runtime.start_execution(tenant_id=tenant_text, lease_id=lease_id, worker_id=f"provider-failure-{sequence}")
            setup.commit()
            with patch(
                "backend.services.tools.standalone_actions._fetch_governed_public_search",
                return_value=_CONTROLLED_PROVIDER_FAILURE,
            ):
                TaskDispatcher(
                    session_factory=factory,
                    vector_session_factory=factory,
                    queue=queue_adapter,
                    worker_id=f"provider-failure-{sequence}",
                    tenant_id=tenant_text,
                ).execute(task_id=claimed.id, lease_id=lease_id)
            setup.expire_all()
            tasks = list(
                setup.scalars(
                    select(ExecutionTask).where(
                        ExecutionTask.tenant_id == tenant_text,
                        ExecutionTask.mission_id == mission_id,
                    )
                )
            )
            verifier = next(
                (
                    task
                    for task in tasks
                    if task.metadata_json["tool_invocation"]["action"] == "research.verify_public_candidates"
                ),
                None,
            )
            if verifier is not None and verifier.status == ExecutionTaskState.FAILED.value:
                break
        else:
            raise AssertionError("provider failure did not reach the verifier runtime boundary")
    finally:
        setup.close()

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_text)
        tasks = list(
            verify.scalars(
                select(ExecutionTask).where(
                    ExecutionTask.tenant_id == tenant_text,
                    ExecutionTask.mission_id == mission_id,
                )
            )
        )
        research = next(task for task in tasks if task.metadata_json["tool_invocation"]["action"] == "web.research")
        verifier = next(
            task
            for task in tasks
            if task.metadata_json["tool_invocation"]["action"] == "research.verify_public_candidates"
        )
        research_output = research.metadata_json["handler_result"]["output"]
        assert research.status == ExecutionTaskState.COMPLETED.value
        assert research_output["public_search_real"] is False
        assert research_output["valid_empty_result"] is None
        attempts = research_output["provider_attempts"]
        assert [attempt["query"] for attempt in attempts] == research_output["search_queries"]
        assert all(
            {
                "provider": "duckduckgo_html",
                "outcome": "failure",
                "result_count": 0,
                "status_code": None,
                "error": "controlled provider timeout",
            }.items()
            <= attempt.items()
            for attempt in attempts
        )
        assert verifier.status == ExecutionTaskState.FAILED.value
        failure = verifier.metadata_json["failure"]
        assert failure["code"] == "HANDLER_FAILED"
        assert "input binding failed" in failure["message"]
        assert "no upstream prospects" in failure["message"]
    finally:
        verify.close()


def test_completed_empty_public_search_materializes_insufficient_evidence_artifacts(pg_engine, queue_adapter) -> None:
    """A successful search with no results completes the entire read-only graph.

    The controlled provider result represents a real provider exchange with no
    candidate URLs. PostgreSQL and Redis remain real: this proves the marker
    crosses composition, binding, queue, lease, dispatch, evidence persistence,
    and fresh-session artifact readback without turning empty discovery into a
    provider failure or a synthetic prospect.
    """

    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(Tenant(id=tenant_id, name="Empty public research", slug=f"empty-{tenant_id.hex[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()

        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
            patch(
                "backend.services.tools.standalone_actions._fetch_governed_public_search",
                return_value=_CONTROLLED_PROVIDER_EMPTY,
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed_response = client.post("/v1/missions/compose", json={"instruction": _INSTRUCTION})
            assert composed_response.status_code == 200, composed_response.text
            composed = composed_response.json()
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "provider-empty-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            setup.commit()
            _drain_mission(
                session=setup,
                factory=factory,
                queue_adapter=queue_adapter,
                tenant_id=tenant_text,
                mission_id=mission_id,
            )
    finally:
        setup.close()

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_text)
        tasks = list(
            verify.scalars(
                select(ExecutionTask).where(
                    ExecutionTask.tenant_id == tenant_text,
                    ExecutionTask.mission_id == mission_id,
                )
            )
        )
        assert tasks and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks)
        leases = list(verify.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_text)))
        assert leases and all(lease.status == WorkerLeaseState.RELEASED.value for lease in leases)
        outputs = {
            task.metadata_json["tool_invocation"]["action"]: task.metadata_json["handler_result"]["output"]
            for task in tasks
        }
        research_output = outputs["web.research"]
        assert research_output["public_search_real"] is True
        assert research_output["web_results"] == []
        assert research_output["valid_empty_result"]["classification"] == "valid_empty"
        assert research_output["search_providers"] == ["controlled_governed_search"]
        assert len(research_output["provider_attempts"]) == len(research_output["search_queries"])
        assert all(attempt["outcome"] == "empty" for attempt in research_output["provider_attempts"])

        verifier_output = outputs["research.verify_public_candidates"]
        qualification_output = outputs["sales.qualify"]
        assert verifier_output["verified_prospect_candidates"] == []
        assert verifier_output["valid_empty_result"]["classification"] == "valid_empty"
        assert qualification_output["qualified_prospects"] == []
        assert qualification_output["valid_empty_result"]["classification"] == "valid_empty"

        artifacts = collect_materialized_artifacts(tasks)
        assert next(item.payload for item in artifacts if item.artifact_key == "verified_prospect_candidates") == []
        assert next(item.payload for item in artifacts if item.artifact_key == "qualified_prospects") == []
        evidence = list(
            verify.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.tenant_id == tenant_text,
                    EvidenceRecord.mission_id == mission_id,
                )
            )
        )
        assert {task.id for task in tasks} <= {item.execution_task_id for item in evidence}
        assert any(item.evidence_source == "tool.invoke.web.research" for item in evidence)

        # The tenant-scoped operator read model must retain the completed-empty
        # outcome.  It must not reinterpret it as a prospect or hide its durable
        # evidence merely because the requested count was not met.
        read_app = _build_app(tenant_id=tenant_id, session=verify, queue_adapter=queue_adapter)
        response = TestClient(read_app, raise_server_exceptions=False).get(f"/v1/missions/{mission_id}/deliverable")
        assert response.status_code == 200, response.text
        deliverable = response.json()
        assert deliverable["kind"] == "revops_report"
        assert deliverable["prospects"] == []
        assert deliverable["artifacts"]["verified_prospect_candidates"] == []
        assert deliverable["artifacts"]["qualified_prospects"] == []
        assert deliverable["task_state"]["all_succeeded"] is True
        assert deliverable["completion"]["complete"] is False
        assert deliverable["evidence_references"]

        foreign_tenant_id = uuid.uuid4()
        foreign = factory()
        try:
            foreign.add(
                Tenant(
                    id=foreign_tenant_id,
                    name="Foreign deliverable reader",
                    slug=f"foreign-{foreign_tenant_id.hex[:8]}",
                    plan="free",
                )
            )
            foreign.flush()
            activate_tenant_session(foreign, str(foreign_tenant_id))
            foreign.commit()
            foreign_app = _build_app(tenant_id=foreign_tenant_id, session=foreign, queue_adapter=queue_adapter)
            foreign_response = TestClient(foreign_app, raise_server_exceptions=False).get(
                f"/v1/missions/{mission_id}/deliverable"
            )
            assert foreign_response.status_code == 404
            assert foreign_response.json() == {"detail": "mission not found for tenant"}
        finally:
            foreign.close()
    finally:
        verify.close()


def test_directory_search_hit_is_rejected_as_unverified_identity_through_runtime(pg_engine, queue_adapter) -> None:
    """A real observed directory page cannot become a commercial prospect.

    Provider and page responses are controlled so the test can exercise the
    identity policy deterministically. PostgreSQL and Redis are real, and the
    mission runs through composition, admission, queueing, leasing, dispatch,
    durable evidence, and fresh-session artifact readback.
    """

    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(Tenant(id=tenant_id, name="Directory rejection", slug=f"directory-{tenant_id.hex[:8]}", plan="free"))
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()

        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
            patch(
                "backend.services.tools.standalone_actions._fetch_governed_public_search",
                return_value=_CONTROLLED_DIRECTORY_SEARCH,
            ),
            patch(
                "backend.services.tools.web_action_contacts.fetch_public_page",
                return_value=_CONTROLLED_DIRECTORY_PAGE,
            ),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed_response = client.post("/v1/missions/compose", json={"instruction": _INSTRUCTION})
            assert composed_response.status_code == 200, composed_response.text
            composed = composed_response.json()
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "directory-rejection-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            setup.commit()
            _drain_mission(
                session=setup,
                factory=factory,
                queue_adapter=queue_adapter,
                tenant_id=tenant_text,
                mission_id=mission_id,
            )
    finally:
        setup.close()

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_text)
        tasks = list(
            verify.scalars(
                select(ExecutionTask).where(
                    ExecutionTask.tenant_id == tenant_text,
                    ExecutionTask.mission_id == mission_id,
                )
            )
        )
        assert tasks and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks)
        leases = list(verify.scalars(select(WorkerLease).where(WorkerLease.tenant_id == tenant_text)))
        assert leases and all(lease.status == WorkerLeaseState.RELEASED.value for lease in leases)
        outputs = {
            task.metadata_json["tool_invocation"]["action"]: task.metadata_json["handler_result"]["output"]
            for task in tasks
        }
        research_output = outputs["web.research"]
        assert research_output["public_search_real"] is True
        assert research_output["web_results"]
        assert research_output["provider_attempts"]
        assert all(attempt["outcome"] == "results" for attempt in research_output["provider_attempts"])

        verifier_output = outputs["research.verify_public_candidates"]
        assert verifier_output["pages"][0]["real"] is True
        assert verifier_output["pages"][0]["identity_status"] == "unverified"
        assert verifier_output["pages"][0]["source_reliability"] == "directory_or_third_party"
        assert verifier_output["verified_prospect_candidates"] == []
        assert verifier_output["valid_empty_result"] == {
            "classification": "valid_empty",
            "reason": "completed public identity verification rejected all candidate sources",
        }

        qualification_output = outputs["sales.qualify"]
        assert qualification_output["qualified_prospects"] == []
        assert qualification_output["valid_empty_result"]["classification"] == "valid_empty"
        artifacts = collect_materialized_artifacts(tasks)
        assert next(item.payload for item in artifacts if item.artifact_key == "verified_prospect_candidates") == []
        assert next(item.payload for item in artifacts if item.artifact_key == "qualified_prospects") == []
        evidence = list(
            verify.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.tenant_id == tenant_text,
                    EvidenceRecord.mission_id == mission_id,
                )
            )
        )
        assert {task.id for task in tasks} <= {item.execution_task_id for item in evidence}
    finally:
        verify.close()


def test_public_only_research_does_not_read_or_materialize_tenant_crm_records(pg_engine, queue_adapter) -> None:
    """Public-only composition excludes tenant records before research executes."""

    def _forbidden_internal_read(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("public-only research attempted an internal record or CRM read")

    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(
            Tenant(id=tenant_id, name="Public-only isolation", slug=f"public-only-{tenant_id.hex[:8]}", plan="free")
        )
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        TenantInternalRecordRepository(setup).write_record(
            tenant_id=tenant_text,
            record_type="account",
            record_id="tenant-hvac-account",
            data={
                "name": "Tenant-Owned Dallas HVAC",
                "industry": "HVAC",
                "location": "Dallas",
                "website": "https://tenant-owned.example",
            },
        )
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()

        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
            patch(
                "backend.services.tools.standalone_actions._fetch_governed_public_search",
                return_value=_CONTROLLED_PROVIDER_EMPTY,
            ),
            patch(
                "backend.services.tools.standalone_actions.resolve_record_store", side_effect=_forbidden_internal_read
            ),
            patch("backend.services.tools.standalone_actions.default_crm_client", side_effect=_forbidden_internal_read),
        ):
            client = TestClient(app, raise_server_exceptions=False)
            composed_response = client.post("/v1/missions/compose", json={"instruction": _INSTRUCTION})
            assert composed_response.status_code == 200, composed_response.text
            composed = composed_response.json()
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "public-only-isolation-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            setup.commit()
            _drain_mission(
                session=setup,
                factory=factory,
                queue_adapter=queue_adapter,
                tenant_id=tenant_text,
                mission_id=mission_id,
            )
    finally:
        setup.close()

    verify = factory()
    try:
        activate_tenant_session(verify, tenant_text)
        tasks = list(
            verify.scalars(
                select(ExecutionTask).where(
                    ExecutionTask.tenant_id == tenant_text,
                    ExecutionTask.mission_id == mission_id,
                )
            )
        )
        assert tasks and all(task.status == ExecutionTaskState.COMPLETED.value for task in tasks)
        research = next(task for task in tasks if task.metadata_json["tool_invocation"]["action"] == "web.research")
        output = research.metadata_json["handler_result"]["output"]
        assert output["exclude_internal_records"] is True
        assert output["internal_records"] == []
        assert output["internal_prospect_candidates"] == []
        assert output["crm_brain_matches"] == []
        assert output["source_partitions"]["tenant_internal"] == {
            "record_count": 0,
            "candidate_count": 0,
            "verified_candidate_count": 0,
            "evidence_class": "tenant_owned_record",
            "provider_observed": False,
            "authority": "tenant_record_store",
        }
    finally:
        verify.close()
