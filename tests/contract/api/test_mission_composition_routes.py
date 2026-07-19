"""Contract tests for mission composition compose/confirm boundaries."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import mission_composition as composition_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.domain.enums import MissionPlanStatus
from backend.domain.mission import MISSION_INTAKE_METADATA_KEY, MISSION_TASK_GRAPH_METADATA_KEY, Mission, MissionPlan
from backend.services.mission_composition.proposal_store import clear_proposals_for_tests

ROOFING_INSTRUCTION = (
    "Research roofing companies in Austin, identify three strong prospects, "
    "draft personalized introductions, and bring them to me before anything is sent."
)


def setup_function() -> None:
    clear_proposals_for_tests()


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=("tenant_admin",),
        )
        return await call_next(request)

    app.include_router(composition_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def test_compose_returns_proposal_without_runtime_authority() -> None:
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    app = _build_app(tenant_id)
    with (
        patch.object(composition_module, "require_route_permission", return_value=None),
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_repo_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_repo_cls,
    ):
        profile_repo_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_repo_cls.return_value.list_for_tenant.return_value = []
        client = TestClient(app)
        response = client.post("/v1/missions/compose", json={"instruction": ROOFING_INSTRUCTION})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["proposal_id"]
    assert body["grants_execution_authority"] is False
    assert body["authority_class"] == "read_model"
    assert "gtm.email_send" not in body["allowed_actions"]
    assert body["allowed_actions"]
    assert body["task_graph_preview"]["nodes"]
    assert body["composition"]["allowed_actions_provenance"]["selected_by"] == "mission_composition_engine"
    assert body["ready_to_start"] is True


def test_confirm_creates_mission_plan_graph_not_queue() -> None:
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    mission_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    plan_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    app = _build_app(tenant_id)

    plan = MissionPlan(
        id=plan_id,
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        status=MissionPlanStatus.DRAFT.value,
        metadata_json={},
    )

    def _add_mission(m: Mission) -> Mission:
        m.id = mission_id
        m.metadata_json = dict(m.metadata_json or {})
        return m

    with (
        patch.object(composition_module, "require_route_permission", return_value=None),
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_repo_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_repo_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
        patch("backend.services.mission_composition.service.QuotaEnforcementService") as quota_cls,
    ):
        profile_repo_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_repo_cls.return_value.list_for_tenant.return_value = []
        quota_cls.return_value.enforce_mission_budget_gate.return_value = None
        quota_cls.return_value.check_and_record_mission_creation.return_value = None
        mission_repo_cls.return_value.add.side_effect = _add_mission
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = plan

        client = TestClient(app)
        compose = client.post("/v1/missions/compose", json={"instruction": ROOFING_INSTRUCTION})
        assert compose.status_code == 200, compose.text
        proposal_id = compose.json()["proposal_id"]
        composition = compose.json()["composition"]

        confirm = client.post(
            f"/v1/missions/proposals/{proposal_id}/confirm",
            json={"composition": composition},
        )

    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["mission_id"] == str(mission_id)
    assert body["plan_id"] == str(plan_id)
    assert body["runtime_queued"] is False
    assert body["grants_execution_authority"] is False
    assert "runtime-queue-admission" in " ".join(body["next_steps"])
    assert "gtm.email_send" not in body["allowed_actions"]
    assert MISSION_TASK_GRAPH_METADATA_KEY in body["task_graph"] or body["task_graph"].get("nodes") is not None

    # Mission metadata must include intake and not imply queue admission.
    added: Mission = mission_repo_cls.return_value.add.call_args[0][0]
    assert MISSION_INTAKE_METADATA_KEY in (added.metadata_json or {})
    intake = (added.metadata_json or {})[MISSION_INTAKE_METADATA_KEY]
    assert "gtm.email_send" not in intake.get("allowed_actions", [])
