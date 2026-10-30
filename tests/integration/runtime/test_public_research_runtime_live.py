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
from backend.domain.evidence import EvidenceRecord
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
        assert "binding_required" in verifier.metadata_json["failure"]["message"]
    finally:
        verify.close()
