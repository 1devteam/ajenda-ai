"""Opt-in real public-web proof for the governed research runtime path.

This is intentionally opt-in: it contacts public websites and search endpoints,
so it cannot be a deterministic CI fixture.  It still uses real PostgreSQL,
Redis, composition routes, graph admission, leases, TaskDispatcher, and a
fresh-session artifact readback.  No CRM writes, messages, or browser actions
are authorized by this mission.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from backend.api.routes import mission as mission_module
from backend.api.routes import mission_composition as composition_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.principal import Principal, PrincipalType
from backend.db.tenant_session import activate_tenant_session
from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.domain.execution_task import ExecutionTask
from backend.domain.tenant import Tenant
from backend.domain.worker_lease import WorkerLease
from backend.services.mission_composition.deliverable_runtime_artifacts import collect_materialized_artifacts
from backend.services.mission_composition.proposal_store import clear_proposals_for_tests
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher
from tests.integration.operating_charter_support import persist_test_operating_charter

pytestmark = pytest.mark.integration

_LIVE_FLAG = "AJENDA_LIVE_PUBLIC_RESEARCH"
_INSTRUCTION = (
    "Research and qualify up to three HVAC companies in Dallas using public sources only. "
    "Do not contact anyone or modify any external system."
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
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: session
    app.dependency_overrides[get_queue_adapter] = lambda: queue_adapter
    return app


def _drain_mission(*, session, factory, queue_adapter, tenant_id: str, mission_id: uuid.UUID) -> None:
    """Run every admitted task through the real claim, lease, and dispatcher path."""

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
                }
                for task in tasks
            ]
        )
    )


def test_live_public_research_preserves_verified_or_insufficient_evidence_artifact(
    pg_engine,
    queue_adapter,
) -> None:
    """A provider-successful empty result is a completed evidence outcome, not a binding failure."""

    if os.environ.get(_LIVE_FLAG) != "1":
        pytest.skip(f"set {_LIVE_FLAG}=1 to run the external read-only public research proof")

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
            assert "research.observe_contacts" not in {step["action_name"] for step in composed["planned_steps"]}
            confirmed_response = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"], "idempotency_key": "live-public-research-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            launched = launched_response.json()
            assert launched["runtime_admitted"] is True
            assert launched["queued_task_ids"]
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
        research_output = research_task.metadata_json["handler_result"]["output"]
        assert research_output["source"] == "public_search"
        assert research_output["exclude_internal_records"] is True
        assert research_output["public_search_attempts"]
        assert all("provider" in item for item in research_output["public_search_attempts"])

        artifacts = collect_materialized_artifacts(tasks)
        verified = next((item for item in artifacts if item.artifact_key == "verified_prospect_candidates"), None)
        qualified = next((item for item in artifacts if item.artifact_key == "qualified_prospects"), None)
        assert verified is not None, {
            "artifacts": [item.artifact_key for item in artifacts],
            "tasks": [
                {
                    "action": task.metadata_json.get("tool_invocation", {}).get("action"),
                    "expected_output": task.metadata_json.get("expected_output_contract"),
                    "output_keys": sorted((task.metadata_json.get("handler_result", {}).get("output") or {}).keys()),
                }
                for task in tasks
            ],
        }
        assert qualified is not None
        assert isinstance(verified.payload, list)
        assert isinstance(qualified.payload, list)
        if not verified.payload:
            verify_output = next(
                task.metadata_json["handler_result"]["output"]
                for task in tasks
                if task.metadata_json["tool_invocation"]["action"] == "research.verify_public_candidates"
            )
            assert isinstance(verify_output.get("research_gap"), str) and verify_output["research_gap"].strip()
    finally:
        verify.close()


def test_live_browser_observation_runs_through_composed_queue_and_fresh_readback(
    pg_engine,
    queue_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A browser observation remains a bounded external-read task, not a side path."""

    if os.environ.get(_LIVE_FLAG) != "1":
        pytest.skip(f"set {_LIVE_FLAG}=1 to run the external read-only browser proof")

    monkeypatch.setenv("AJENDA_BROWSER_SESSION_ENABLED", "true")
    from backend.app.config import get_settings

    get_settings.cache_clear()
    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    tenant_text = str(tenant_id)
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = factory()
    try:
        setup.add(
            Tenant(id=tenant_id, name="Live browser observation", slug=f"browser-{tenant_id.hex[:8]}", plan="free")
        )
        setup.flush()
        activate_tenant_session(setup, tenant_text)
        persist_test_operating_charter(setup, tenant_id=tenant_text)
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        setup.commit()

        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        instruction = (
            "Observe https://example.com and return the page title and visible text. Do not send or modify anything."
        )
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
                json={"composition": composed["composition"], "idempotency_key": "live-browser-observation-v1"},
            )
            assert confirmed_response.status_code == 200, confirmed_response.text
            mission_id = uuid.UUID(confirmed_response.json()["mission_id"])
            launched_response = client.post(f"/v1/missions/{mission_id}/launch")
            assert launched_response.status_code == 200, launched_response.text
            assert launched_response.json()["runtime_admitted"] is True
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
        get_settings.cache_clear()

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
        assert output["real"] is True
        assert output["browser_ready"] is True
        assert observation["network_provenance"]["engine"] == "playwright_chromium"
        assert observation["network_provenance"]["request_vetting"] == "network_egress_per_request"
        assert observation["network_provenance"]["allowed_hosts"] == ["example.com"]
    finally:
        verify.close()
