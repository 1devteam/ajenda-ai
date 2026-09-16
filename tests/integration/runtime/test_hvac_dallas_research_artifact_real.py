"""Complete HVAC Dallas research must persist prospect_candidates after lease/start.

Walks the existing ladder only: compose → confirm → launch (compile, runtime
admission, task materialization, queue admission) → claim/lease → start →
dispatcher. Confirm does not execute tools. Incomplete "Find companies" stays
gaps_open and cannot confirm.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
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
from backend.repositories.tenant_internal_record_repository import TenantInternalRecordRepository
from backend.services.mission_composition.deliverable_runtime_artifacts import collect_materialized_artifacts
from backend.services.mission_composition.proposal_store import clear_proposals_for_tests
from backend.services.quota_enforcement import QuotaEnforcementService
from backend.services.worker_runtime_service import WorkerRuntimeService
from backend.workers.task_dispatcher import TaskDispatcher

pytestmark = pytest.mark.integration

HVAC_DALLAS = "Find 10 HVAC companies in Dallas"
INCOMPLETE = "Find companies"

_HVAC_DALLAS_ACCOUNTS = (
    ("Dallas Comfort HVAC", "dallascomfort.example"),
    ("North Texas Air Pros", "ntairpros.example"),
    ("Oak Cliff Cooling", "oakcliffcooling.example"),
    ("Plano Premier Heat", "planopremierheat.example"),
    ("Irving Climate Control", "irvingclimate.example"),
    ("Garland Air Systems", "garlandair.example"),
    ("Mesquite Mechanical HVAC", "mesquitehvac.example"),
    ("Richardson Cool Air", "richardsoncool.example"),
    ("Farmers Branch Heating", "fbheating.example"),
    ("Deep Ellum HVAC Co", "deepellumhvac.example"),
)


def _build_app(*, tenant_id: uuid.UUID, session, queue_adapter) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="hvac-dallas-operator",
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


def test_hvac_dallas_research_persists_prospect_candidates_after_start(pg_engine, queue_adapter, redis_client) -> None:
    clear_proposals_for_tests()
    tenant_id = uuid.uuid4()
    worker_id = "worker-hvac-dallas-research"
    session_factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    setup = session_factory()
    try:
        activate_tenant_session(setup, str(tenant_id))
        setup.add(Tenant(id=tenant_id, name="HVAC Dallas Tenant", slug=f"hvac-{tenant_id.hex[:8]}", plan="free"))
        setup.flush()
        QuotaEnforcementService(setup).check_and_record_mission_creation(tenant_id)
        repo = TenantInternalRecordRepository(setup)
        for index, (name, host) in enumerate(_HVAC_DALLAS_ACCOUNTS, start=1):
            repo.write_record(
                tenant_id=str(tenant_id),
                record_type="account",
                record_id=f"hvac-dallas-{index}",
                data={
                    "name": name,
                    "industry": "HVAC",
                    "location": "Dallas",
                    "website": f"https://{host}",
                    "product_description": f"{name} provides HVAC service in Dallas.",
                    "research_summary": f"{name} is an HVAC company in Dallas.",
                    "sources": [f"https://{host}"],
                },
            )
        setup.commit()

        app = _build_app(tenant_id=tenant_id, session=setup, queue_adapter=queue_adapter)
        with (
            patch.object(composition_module, "require_route_permission", return_value=None),
            patch.object(mission_module, "require_route_permission", return_value=None),
        ):
            client = TestClient(app, raise_server_exceptions=False)

            incomplete = client.post("/v1/missions/compose", json={"instruction": INCOMPLETE})
            assert incomplete.status_code == 200, incomplete.text
            incomplete_body = incomplete.json()
            assert incomplete_body["proposal_status"] == "gaps_open"
            assert incomplete_body["ready_to_start"] is False
            assert "research.discover_prospects" in (
                incomplete_body.get("composition", {}).get("intelligence_envelope", {}) or {}
            ).get("named_job_keys", [])
            blocked = client.post(
                f"/v1/missions/proposals/{incomplete_body['proposal_id']}/confirm",
                json={"composition": incomplete_body["composition"]},
            )
            assert blocked.status_code == 422, blocked.text
            assert blocked.json()["detail"]["code"] in {"PROPOSAL_NOT_READY", "NO_RUNTIME_ACTIONS"}

            compose = client.post("/v1/missions/compose", json={"instruction": HVAC_DALLAS})
            assert compose.status_code == 200, compose.text
            composed = compose.json()
            assert composed["proposal_status"] == "proposal_ready"
            assert composed["ready_to_start"] is True
            envelope = composed.get("composition", {}).get("intelligence_envelope") or {}
            assert "research.discover_prospects" in envelope.get("named_job_keys", [])
            queries = [step.get("tool_input", {}).get("query") for step in composed.get("planned_steps") or []]
            assert queries
            assert all(query != "companies" for query in queries)
            assert any(isinstance(query, str) and "HVAC" in query and "Dallas" in query for query in queries)

            confirm = client.post(
                f"/v1/missions/proposals/{composed['proposal_id']}/confirm",
                json={"composition": composed["composition"]},
            )
            assert confirm.status_code == 200, confirm.text
            confirmed = confirm.json()
            assert confirmed["runtime_queued"] is False
            assert confirmed["grants_execution_authority"] is False
            mission_id = confirmed["mission_id"]

            launch = client.post(f"/v1/missions/{mission_id}/launch")
            assert launch.status_code == 200, launch.text
            launched = launch.json()
            assert launched["compile_status"] == "ready"
            assert launched["runtime_admitted"] is True
            queued_task_ids = launched["queued_task_ids"]
            assert queued_task_ids, launched
        setup.commit()
        task_id = uuid.UUID(queued_task_ids[0])
        runtime = WorkerRuntimeService(setup, queue_adapter)
        claimed = runtime.claim_next_task(tenant_id=str(tenant_id), worker_id=worker_id)
        assert claimed is not None
        assert claimed.id == task_id
        lease_id = uuid.UUID(str(claimed.metadata_json["worker_lease_id"]))
        runtime.heartbeat(tenant_id=str(tenant_id), lease_id=lease_id, worker_id=worker_id)
        runtime.start_execution(tenant_id=str(tenant_id), lease_id=lease_id, worker_id=worker_id)
        setup.commit()
    finally:
        setup.close()

    TaskDispatcher(
        session_factory=session_factory,
        queue=queue_adapter,
        worker_id=worker_id,
        tenant_id=str(tenant_id),
    ).execute(task_id=task_id, lease_id=lease_id)

    verify = session_factory()
    try:
        activate_tenant_session(verify, str(tenant_id))
        final_task = verify.get(ExecutionTask, task_id)
        final_lease = verify.get(WorkerLease, lease_id)
        assert final_task is not None
        assert final_task.status == ExecutionTaskState.COMPLETED.value
        assert final_lease is not None
        assert final_lease.status == WorkerLeaseState.RELEASED.value
        artifacts = collect_materialized_artifacts([final_task])
        candidates = next((item for item in artifacts if item.artifact_key == "prospect_candidates"), None)
        assert candidates is not None
        assert isinstance(candidates.payload, list)
        assert len(candidates.payload) == 10
        companies = {str(row.get("company") or "") for row in candidates.payload if isinstance(row, dict)}
        assert "pending" not in {name.casefold() for name in companies}
        assert "companies" not in {name.casefold() for name in companies}
        assert redis_client.llen(f"ajenda:queue:{tenant_id}:processing") == 0
    finally:
        verify.close()
