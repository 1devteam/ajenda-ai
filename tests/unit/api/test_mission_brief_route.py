from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import mission_brief as mission_brief_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.domain.business_profile import BusinessProfile


class _FakeBusinessProfileRepository:
    def __init__(self, profile: BusinessProfile | None = None) -> None:
        self.profile = profile
        self.read_count = 0

    def get_active_profile_for_tenant(self, *, tenant_id: str) -> BusinessProfile | None:
        self.read_count += 1
        if self.profile is not None and self.profile.tenant_id == tenant_id and self.profile.status == "active":
            return self.profile
        return None


def _profile(
    *, tenant_id: str, facts: dict[str, object], provenance: dict[str, object] | None = None
) -> BusinessProfile:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    profile = BusinessProfile(tenant_id=tenant_id, approved_facts=facts, provenance=provenance or {})
    profile.id = uuid.uuid4()
    profile.created_at = now
    profile.updated_at = now
    return profile


def _client(
    tenant_id: uuid.UUID,
    *,
    db: MagicMock | None = None,
    roles: tuple[str, ...] = ("tenant_admin",),
) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _inject_principal(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.principal = Principal(
            subject_id="test-user",
            tenant_id=str(tenant_id),
            principal_type=PrincipalType.USER,
            roles=roles,
        )
        return await call_next(request)

    app.include_router(mission_brief_module.router, prefix="/v1")
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: db or MagicMock()
    return TestClient(app, raise_server_exceptions=False)


def test_mission_brief_draft_merges_profile_defaults_without_creating_mission_or_runtime_work() -> None:
    tenant_id = uuid.uuid4()
    db = MagicMock()
    repo = _FakeBusinessProfileRepository(
        _profile(
            tenant_id=str(tenant_id),
            facts={
                "business_name": {"value": "Ajenda AI"},
                "allowed_actions": {"value": ["read_crm", "draft_recommendations"]},
                "allowed_tools": {"value": ["crm", "analytics"]},
                "default_jurisdiction": {"value": "US-ALL"},
                "approval_required": {"value": True},
            },
            provenance={
                "allowed_actions": {"actor_id": "profile-admin", "decision": "direct_update"},
                "default_jurisdiction": {"actor_id": "profile-admin", "decision": "direct_update"},
            },
        )
    )

    with (
        patch.object(mission_brief_module, "BusinessProfileRepository", return_value=repo),
        patch("backend.services.mission_executor.MissionExecutor") as mission_executor,
        patch("backend.services.execution_coordinator.ExecutionCoordinator") as execution_coordinator,
        patch("backend.repositories.mission_repository.MissionRepository") as mission_repository,
        patch("backend.repositories.execution_task_repository.ExecutionTaskRepository") as execution_task_repository,
        patch("backend.repositories.worker_lease_repository.WorkerLeaseRepository") as worker_lease_repository,
        patch("backend.repositories.evidence_repository.EvidenceRepository") as evidence_repository,
        patch("backend.repositories.outcome_review_repository.OutcomeReviewRepository") as outcome_review_repository,
        patch("backend.repositories.retrieval_contract_repository.RetrievalContractRepository") as retrieval_repository,
    ):
        response = _client(tenant_id, db=db).post(
            "/v1/mission-briefs/draft",
            json={
                "current_intent": {
                    "objective": "Review stale qualified leads and recommend next actions.",
                    "success_criteria": [
                        {
                            "description": "Every stale qualified lead has a recommended next action.",
                            "evidence": ["lead review summary"],
                        }
                    ],
                    "jurisdiction": "US-NY",
                },
                "request_context": {"conversation_id": "conv-1"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["authority_flags"] == {
        "authority_class": "read_model",
        "mutation_allowed": False,
        "creates_mission": False,
        "creates_mission_plan": False,
        "creates_task_graph": False,
        "creates_execution_tasks": False,
        "queues_work": False,
        "creates_worker_leases": False,
        "creates_evidence_or_outcomes": False,
        "creates_retrieval_or_memory_records": False,
        "runtime_authority": False,
        "requires_explicit_mission_create": True,
        "business_profile_is_runtime_authority": False,
    }
    assert body["readiness"]["ready_for_mission_create"] is True
    assert body["suggested_mission_create"]["allowed_actions"] == ["read_crm", "draft_recommendations"]
    assert body["suggested_mission_create"]["allowed_tools"] == ["crm", "analytics"]
    assert body["suggested_mission_create"]["approval_required"] is True
    assert body["suggested_mission_create"]["jurisdiction"] == "US-NY"
    assert body["provenance"]["fields"]["allowed_actions"]["source"] == "business_profile"
    assert "allowed_actions" in body["provenance"]["profile_facts_used"]
    assert body["provenance"]["fields"]["jurisdiction"]["source"] == "mission_input"
    assert body["provenance"]["conflicts"][0]["field"] == "jurisdiction"
    assert body["provenance"]["conflicts"][0]["resolution"] == "mission_input_wins"
    assert body["brief"]["business_profile_context"]["business_name"] == "Ajenda AI"
    db.add.assert_not_called()
    mission_executor.assert_not_called()
    execution_coordinator.assert_not_called()
    mission_repository.assert_not_called()
    execution_task_repository.assert_not_called()
    worker_lease_repository.assert_not_called()
    evidence_repository.assert_not_called()
    outcome_review_repository.assert_not_called()
    retrieval_repository.assert_not_called()


def test_mission_brief_reports_missing_required_mission_intent_without_fabricating_mission_create() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository(
        _profile(
            tenant_id=str(tenant_id),
            facts={"business_name": {"value": "Ajenda AI"}, "allowed_tools": {"value": ["crm"]}},
        )
    )

    with patch.object(mission_brief_module, "BusinessProfileRepository", return_value=repo):
        response = _client(tenant_id).post("/v1/mission-briefs/draft", json={"current_intent": {}})

    assert response.status_code == 200
    body = response.json()
    assert body["readiness"] == {"ready_for_mission_create": False, "blocker_count": 2, "warning_count": 1}
    assert {item["field"] for item in body["missing_information"] if item["severity"] == "blocker"} == {
        "objective",
        "success_criteria",
    }
    assert "objective" not in body["suggested_mission_create"]
    assert "success_criteria" not in body["suggested_mission_create"]
    assert body["suggested_mission_create"]["allowed_tools"] == ["crm"]


def test_mission_brief_requires_mission_create_and_business_profile_read_permissions() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()

    with patch.object(mission_brief_module, "BusinessProfileRepository", return_value=repo):
        response = _client(tenant_id, roles=("viewer",)).post("/v1/mission-briefs/draft", json={})

    assert response.status_code == 403
    assert response.json() == {"detail": "missing permission: mission:create"}
    assert repo.read_count == 0


def test_mission_brief_rejects_oversized_request_context_before_repository_access() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()

    with patch.object(mission_brief_module, "BusinessProfileRepository", return_value=repo):
        response = _client(tenant_id).post(
            "/v1/mission-briefs/draft",
            json={"request_context": {"value": "x" * (mission_brief_module.MAX_MISSION_BRIEF_JSON_BYTES + 1)}},
        )

    assert response.status_code == 422
    assert repo.read_count == 0
