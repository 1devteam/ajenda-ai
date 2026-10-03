from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import ANY, MagicMock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import mission_deliverable as route_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.mission import Mission
from backend.domain.outcome_review import OutcomeReview
from backend.services.mission_composition.deliverable_contract import extract_deliverable_request
from backend.services.mission_composition.deliverable_runtime_state import (
    DELIVERABLE_RUNTIME_STATE_METADATA_KEY,
    build_deliverable_runtime_state,
)


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

    app.include_router(route_module.router, prefix="/v1")
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: MagicMock()
    return app


def _mission(*, tenant_id: str, instruction: str) -> Mission:
    request = extract_deliverable_request(instruction)
    assert request is not None
    state = build_deliverable_runtime_state(request)
    assert state is not None
    mission = Mission(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        objective="Return a typed RevOps report.",
        status="running",
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json={
            "mission_intake": {
                "context": {
                    "composition": {
                        DELIVERABLE_RUNTIME_STATE_METADATA_KEY: state,
                    }
                }
            }
        },
    )
    mission.created_at = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
    mission.updated_at = mission.created_at
    return mission


def _task(*, mission: Mission, artifact: str, payload: object) -> ExecutionTask:
    task = ExecutionTask(
        id=uuid.uuid4(),
        tenant_id=mission.tenant_id,
        mission_id=mission.id,
        title="Mission deliverable route task",
        description="Materialize a requested artifact.",
        status=ExecutionTaskState.COMPLETED.value,
        metadata_json={
            "expected_output_contract": {"artifact": artifact},
            "handler_result": {
                "handler": "artifact-test",
                "status": "completed",
                "output": {artifact: payload},
            },
        },
        requires_human_review=False,
    )
    task.created_at = datetime(2026, 8, 30, 12, 5, tzinfo=UTC)
    task.updated_at = task.created_at
    return task


def _profile_task(*, mission: Mission, payload: object) -> ExecutionTask:
    return _task(mission=mission, artifact="business_profile_facts", payload=payload)


def _repositories(monkeypatch, *, mission: Mission | None, tasks: list[ExecutionTask]):
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = mission
    task_repo = MagicMock()
    task_repo.list_for_mission_for_tenant.return_value = tasks
    evidence_repo = MagicMock()
    evidence_repo.list_for_mission.return_value = []
    review_repo = MagicMock()
    review_repo.list_for_mission.return_value = []
    monkeypatch.setattr(route_module, "MissionRepository", lambda _db: mission_repo)
    monkeypatch.setattr(route_module, "ExecutionTaskRepository", lambda _db: task_repo)
    monkeypatch.setattr(route_module, "EvidenceRepository", lambda _db: evidence_repo)
    monkeypatch.setattr(route_module, "OutcomeReviewRepository", lambda _db: review_repo)
    return mission_repo, task_repo, evidence_repo, review_repo


def test_route_returns_tenant_scoped_artifact_backed_deliverable(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission = _mission(tenant_id=str(tenant_id), instruction="Return company name.")
    task = _task(
        mission=mission,
        artifact="qualified_prospects",
        payload=[
            {
                "prospect_id": "p1",
                "company": "Acme",
                "score": 80,
                "reasons": ["fit"],
                "qualification_evidence": {"source_references": ["https://acme.example"]},
                "ajenda_relevance": "Ajenda may be relevant to an observed workflow.",
            }
        ],
    )
    repos = _repositories(monkeypatch, mission=mission, tasks=[task])
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    response = client.get(f"/v1/missions/{mission.id}/deliverable")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "revops_report"
    assert body["mission_id"] == str(mission.id)
    assert body["prospects"][0]["company_name"] == "Acme"
    assert body["completion"]["requested_fields"] == ["company_name"]
    assert body["completion"]["complete"] is True
    assert body["task_state"]["all_succeeded"] is True
    assert body["grants_execution_authority"] is False
    repos[0].get_for_tenant.assert_called_once_with(mission_id=mission.id, tenant_id=str(tenant_id))
    repos[1].list_for_mission_for_tenant.assert_called_once_with(
        mission_id=mission.id,
        tenant_id=str(tenant_id),
    )
    repos[2].list_for_mission.assert_called_once_with(mission_id=mission.id, tenant_id=str(tenant_id))
    repos[3].list_for_mission.assert_called_once_with(mission_id=mission.id, tenant_id=str(tenant_id))


def test_profile_route_returns_dedicated_profile_deliverable(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission = _mission(tenant_id=str(tenant_id), instruction="Return company name.")
    profile_id = uuid.uuid4()
    task = _profile_task(
        mission=mission,
        payload={
            "approved_facts": {"business_name": {"value": "Acme"}},
            "profile_brief": {
                "facts": {"business_name": "Acme"},
                "missing_fields": ["description"],
                "conflicting_fields": [],
            },
            "profile_id": str(profile_id),
            "source": "approved_business_profile",
        },
    )
    _repositories(monkeypatch, mission=mission, tasks=[task])
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    response = client.get(f"/v1/missions/{mission.id}/profile-deliverable")

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "business_profile_brief"
    assert body["profile_id"] == str(profile_id)
    assert body["profile_brief"]["facts"]["business_name"] == "Acme"
    assert body["missing_fields"] == ["description"]
    assert body["complete"] is True


def test_knowledge_change_proposals_are_read_only_and_tenant_scoped(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission = _mission(tenant_id=str(tenant_id), instruction="Return company name.")
    _, _, _, review_repo = _repositories(monkeypatch, mission=mission, tasks=[])
    review_repo.list_for_mission.return_value = [
        OutcomeReview(
            id=uuid.uuid4(),
            tenant_id=str(tenant_id),
            mission_id=mission.id,
            evidence_references=[{"evidence_id": "e1", "artifact_id": "artifact-1"}],
            review_status="completed",
            review_decision="inconclusive",
            reviewer_type="human",
            reviewer_source="test",
            review_summary="A repeated terminology mismatch was observed.",
            structured_findings=[{"knowledge_key": "tenant.gtm.aliases", "suggested_change": "Add alias"}],
        )
    ]
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    response = client.get(f"/v1/missions/{mission.id}/knowledge-change-proposals")

    assert response.status_code == 200
    body = response.json()
    assert body["proposals"][0]["target_key"] == "tenant.gtm.aliases"
    assert body["proposals"][0]["grants_execution_authority"] is False
    assert body["proposals"][0]["authority_class"] == "read_model"


def test_route_resolves_current_draft_review_state_through_tenant_scope(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission = _mission(tenant_id=str(tenant_id), instruction="Return drafts.")
    task = _task(
        mission=mission,
        artifact="introduction_drafts",
        payload=[
            {
                "prospect_id": "p1",
                "company": "Acme",
                "artifact_id": "pitch_email-1",
                "subject": "Hello",
            }
        ],
    )
    _repositories(monkeypatch, mission=mission, tasks=[task])
    artifact_reader = MagicMock(
        return_value={
            "mission_id": str(mission.id),
            "review_status": "approved",
            "content": {"subject": "Hello", "body": "Draft body."},
        }
    )
    monkeypatch.setattr(route_module, "read_artifact", artifact_reader)
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    response = client.get(f"/v1/missions/{mission.id}/deliverable")

    assert response.status_code == 200
    draft = response.json()["prospects"][0]["drafts"][0]
    assert draft["review_status"] == "approved"
    assert draft["body"] == "Draft body."
    artifact_reader.assert_called_once_with(
        ANY,
        tenant_id=str(tenant_id),
        artifact_id="pitch_email-1",
    )


def test_route_fails_closed_before_downstream_reads_for_foreign_mission(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    repos = _repositories(monkeypatch, mission=None, tasks=[])
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    response = client.get(f"/v1/missions/{mission_id}/deliverable")

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    repos[1].list_for_mission_for_tenant.assert_not_called()
    repos[2].list_for_mission.assert_not_called()
    repos[3].list_for_mission.assert_not_called()


def test_route_distinguishes_absent_and_invalid_runtime_state(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    mission = _mission(tenant_id=str(tenant_id), instruction="Return company name.")
    mission.metadata_json = {"mission_intake": {}}
    _repositories(monkeypatch, mission=mission, tasks=[])
    client = TestClient(_build_app(tenant_id), raise_server_exceptions=False)

    absent = client.get(f"/v1/missions/{mission.id}/deliverable")

    assert absent.status_code == 404
    assert absent.json() == {"detail": "mission deliverable runtime state not found"}

    mission = _mission(tenant_id=str(tenant_id), instruction="Return company name.")
    state = mission.metadata_json["mission_intake"]["context"]["composition"][DELIVERABLE_RUNTIME_STATE_METADATA_KEY]
    state["grants_execution_authority"] = True
    _repositories(monkeypatch, mission=mission, tasks=[])

    invalid = client.get(f"/v1/missions/{mission.id}/deliverable")

    assert invalid.status_code == 409
    assert invalid.json() == {"detail": "mission deliverable assembly is invalid"}
