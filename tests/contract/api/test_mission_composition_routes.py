"""Contract tests for mission composition compose/confirm boundaries."""

from __future__ import annotations

import uuid
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.api.routes import mission_composition as composition_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.domain.enums import MissionPlanStatus
from backend.domain.mission import MISSION_INTAKE_METADATA_KEY, MISSION_TASK_GRAPH_METADATA_KEY, Mission, MissionPlan
from backend.services.mission_composition.contracts import TargetEntity
from backend.services.mission_composition.proposal_store import clear_proposals_for_tests
from tests.mission_interpreter_fakes import StaticMissionInterpreter, ready_intent

ROOFING_INSTRUCTION = (
    "Research roofing companies in Austin, identify three strong prospects, "
    "draft personalized introductions, and bring them to me before anything is sent."
)


def _interpreter() -> StaticMissionInterpreter:
    return StaticMissionInterpreter(
        ready_intent(
            ROOFING_INSTRUCTION,
            interpreted_instruction=(
                "Research roofing companies in Austin, identify 3 strong prospects, "
                "and draft personalized introductions without sending them."
            ),
            outcomes=("research_prospects", "qualify_prospects", "prepare_outreach"),
            quantity=3,
            targets=[TargetEntity(type="market", industry="roofing", location="Austin")],
        )
    )


def setup_function() -> None:
    clear_proposals_for_tests()


def _build_app(tenant_id: uuid.UUID, db: Session) -> FastAPI:
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

    def _override_db() -> Session:
        return db

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def test_compose_returns_proposal_without_runtime_authority(pg_session: Session) -> None:
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    app = _build_app(tenant_id, pg_session)
    interpreter = _interpreter()
    with (
        patch.object(composition_module, "require_route_permission", return_value=None),
        patch("backend.services.mission_composition.service.build_mission_interpreter", return_value=interpreter),
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
    assert body["interpreted_instruction"] == interpreter.intent.normalized_instruction
    assert body["interpretation_fingerprint"].startswith("sha256:")
    assert body["mission_brief"]["requested_quantity"] == 3
    assert body["mission_brief"]["requested_outcomes"] == [
        "research_prospects",
        "qualify_prospects",
        "prepare_outreach",
    ]
    assert "instruction" not in body
    assert "raw_instruction" not in body
    assert "composition" not in body
    assert "gtm.email_send" not in body["allowed_actions"]
    assert body["allowed_actions"]
    assert body["task_graph_preview"]["nodes"]
    assert body["allowed_actions_provenance"]["selected_by"] == "mission_composition_engine"
    assert body["ready_to_start"] is True


def test_confirm_creates_mission_plan_graph_not_queue(pg_session: Session) -> None:
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    mission_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    plan_id = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    app = _build_app(tenant_id, pg_session)
    interpreter = _interpreter()

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
        patch("backend.services.mission_composition.service.build_mission_interpreter", return_value=interpreter),
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
        fingerprint = compose.json()["interpretation_fingerprint"]

        confirm = client.post(
            f"/v1/missions/proposals/{proposal_id}/confirm",
            json={
                "interpretation_fingerprint": fingerprint,
                "interpretation_confirmed": True,
                "idempotency_key": "2ea4e7ec-0f0f-4679-8854-3a1b601643ef",
            },
        )
        retry_with_new_key = client.post(
            f"/v1/missions/proposals/{proposal_id}/confirm",
            json={
                "interpretation_fingerprint": fingerprint,
                "interpretation_confirmed": True,
                "idempotency_key": "bf236d39-836e-4590-877b-8efdd77d5442",
            },
        )

    assert confirm.status_code == 200, confirm.text
    assert retry_with_new_key.status_code == 200, retry_with_new_key.text
    assert retry_with_new_key.json()["mission_id"] == str(mission_id)
    assert mission_repo_cls.return_value.add.call_count == 1
    body = confirm.json()
    assert body["mission_id"] == str(mission_id)
    assert body["plan_id"] == str(plan_id)
    assert body["runtime_queued"] is False
    assert body["grants_execution_authority"] is False
    next_steps = " ".join(body["next_steps"])
    assert "runtime-admission" in next_steps
    assert "runtime-task-materialization" in next_steps
    assert "runtime-queue-admission" in next_steps
    assert body["next_steps"].index(
        next(step for step in body["next_steps"] if "runtime-admission" in step and "queue" not in step)
    ) < body["next_steps"].index(next(step for step in body["next_steps"] if "runtime-task-materialization" in step))
    assert "gtm.email_send" not in body["allowed_actions"]
    assert MISSION_TASK_GRAPH_METADATA_KEY in body["task_graph"] or body["task_graph"].get("nodes") is not None

    # Mission metadata must include intake and not imply queue admission.
    added: Mission = mission_repo_cls.return_value.add.call_args[0][0]
    assert MISSION_INTAKE_METADATA_KEY in (added.metadata_json or {})
    intake = (added.metadata_json or {})[MISSION_INTAKE_METADATA_KEY]
    assert "gtm.email_send" not in intake.get("allowed_actions", [])
    composition = intake["context"]["composition"]
    assert "instruction" not in composition
    assert composition["interpreted_instruction"] == interpreter.intent.normalized_instruction
    assert composition["interpretation_fingerprint"] == fingerprint
    assert composition["interpretation_confirmed"] is True
    assert composition["intent"]["raw_instruction"] == ""
    assert composition["intent"]["interpretation_evidence"] == []
    assert composition["intent"]["interpreted_clauses"] == []
    assert len(interpreter.calls) == 1


def test_confirm_requires_exact_reviewed_interpretation_and_acknowledgement(pg_session: Session) -> None:
    tenant_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    app = _build_app(tenant_id, pg_session)
    interpreter = _interpreter()
    with (
        patch.object(composition_module, "require_route_permission", return_value=None),
        patch("backend.services.mission_composition.service.build_mission_interpreter", return_value=interpreter),
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_repo_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_repo_cls,
    ):
        profile_repo_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_repo_cls.return_value.list_for_tenant.return_value = []
        client = TestClient(app)
        compose = client.post("/v1/missions/compose", json={"instruction": ROOFING_INSTRUCTION}).json()
        base = {
            "interpretation_fingerprint": compose["interpretation_fingerprint"],
            "idempotency_key": "47b5b821-acad-4413-b2d3-01510d429b33",
        }
        no_ack = client.post(
            f"/v1/missions/proposals/{compose['proposal_id']}/confirm",
            json={**base, "interpretation_confirmed": False},
        )
        wrong_fingerprint = client.post(
            f"/v1/missions/proposals/{compose['proposal_id']}/confirm",
            json={**base, "interpretation_confirmed": True, "interpretation_fingerprint": "sha256:wrong"},
        )
        client_composition = client.post(
            f"/v1/missions/proposals/{compose['proposal_id']}/confirm",
            json={
                **base,
                "interpretation_confirmed": True,
                "composition": {"allowed_actions": ["dangerous.admin_tool"], "ready_to_start": True},
            },
        )

    assert no_ack.status_code == 422
    assert no_ack.json()["detail"]["code"] == "INTERPRETATION_CONFIRMATION_REQUIRED"
    assert wrong_fingerprint.status_code == 422
    assert wrong_fingerprint.json()["detail"]["code"] == "INTERPRETATION_FINGERPRINT_MISMATCH"
    assert client_composition.status_code == 422
    assert len(interpreter.calls) == 1
