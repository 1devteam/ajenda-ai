from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import business_profile as business_profile_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType
from backend.domain.business_profile import BusinessProfile, BusinessProfileSuggestion
from backend.domain.mission import Mission
from backend.repositories.business_profile_repository import BusinessProfileRepository


class _FakeBusinessProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[str, BusinessProfile] = {}
        self.suggestions: dict[uuid.UUID, BusinessProfileSuggestion] = {}
        self.delegate = BusinessProfileRepository(MagicMock())

    def add_profile(self, profile: BusinessProfile) -> BusinessProfile:
        profile.id = profile.id or uuid.uuid4()
        profile.created_at = profile.created_at or datetime(2026, 6, 3, tzinfo=UTC)
        profile.updated_at = profile.updated_at or profile.created_at
        self.profiles[profile.tenant_id] = profile
        return profile

    def get_active_profile_for_tenant(self, *, tenant_id: str) -> BusinessProfile | None:
        profile = self.profiles.get(tenant_id)
        if profile and profile.status == "active":
            return profile
        return None

    def update_profile(self, profile: BusinessProfile) -> BusinessProfile:
        self.profiles[profile.tenant_id] = profile
        return profile

    def upsert_approved_fact(self, **kwargs: object) -> BusinessProfile:
        return self.delegate.upsert_approved_fact(**kwargs)  # type: ignore[arg-type]

    def add_suggestion(self, suggestion: BusinessProfileSuggestion) -> BusinessProfileSuggestion:
        suggestion.id = suggestion.id or uuid.uuid4()
        suggestion.created_at = suggestion.created_at or datetime(2026, 6, 3, tzinfo=UTC)
        self.suggestions[suggestion.id] = suggestion
        return suggestion

    def get_suggestion_for_tenant(
        self, *, suggestion_id: uuid.UUID, tenant_id: str
    ) -> BusinessProfileSuggestion | None:
        suggestion = self.suggestions.get(suggestion_id)
        if suggestion and suggestion.tenant_id == tenant_id:
            return suggestion
        return None

    def list_suggestions_for_tenant(
        self, *, tenant_id: str, status: str | None = None
    ) -> list[BusinessProfileSuggestion]:
        return [
            suggestion
            for suggestion in self.suggestions.values()
            if suggestion.tenant_id == tenant_id and (status is None or suggestion.status == status)
        ]

    def require_pending_suggestion(self, suggestion: BusinessProfileSuggestion) -> None:
        self.delegate.require_pending_suggestion(suggestion)

    def approve_suggestion_as_is(self, **kwargs: object) -> tuple[BusinessProfile, BusinessProfileSuggestion]:
        return self.delegate.approve_suggestion_as_is(**kwargs)  # type: ignore[arg-type]

    def approve_suggestion_with_edit(self, **kwargs: object) -> tuple[BusinessProfile, BusinessProfileSuggestion]:
        return self.delegate.approve_suggestion_with_edit(**kwargs)  # type: ignore[arg-type]

    def decline_suggestion(self, **kwargs: object) -> BusinessProfileSuggestion:
        return self.delegate.decline_suggestion(**kwargs)  # type: ignore[arg-type]

    def dismiss_suggestion(self, **kwargs: object) -> BusinessProfileSuggestion:
        return self.delegate.dismiss_suggestion(**kwargs)  # type: ignore[arg-type]


class _FakeMissionRepository:
    def __init__(self, missions: dict[uuid.UUID, Mission]) -> None:
        self._missions = missions

    def get_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str) -> Mission | None:
        mission = self._missions.get(mission_id)
        if mission and mission.tenant_id == tenant_id:
            return mission
        return None


def _build_app(
    tenant_id: uuid.UUID,
    repo: _FakeBusinessProfileRepository,
    *,
    roles: tuple[str, ...] = ("tenant_admin",),
    missions: dict[uuid.UUID, Mission] | None = None,
) -> FastAPI:
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

    app.include_router(business_profile_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    business_profile_module.BusinessProfileRepository = lambda _db: repo  # type: ignore[assignment]
    business_profile_module.MissionRepository = lambda _db: _FakeMissionRepository(missions or {})  # type: ignore[assignment]
    return app


def _client(
    tenant_id: uuid.UUID,
    repo: _FakeBusinessProfileRepository,
    *,
    roles: tuple[str, ...] = ("tenant_admin",),
    missions: dict[uuid.UUID, Mission] | None = None,
) -> TestClient:
    app = _build_app(tenant_id, repo, roles=roles, missions=missions)
    return TestClient(app, raise_server_exceptions=False)


def _profile(*, tenant_id: str, facts: dict[str, object] | None = None) -> BusinessProfile:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    profile = BusinessProfile(
        tenant_id=tenant_id,
        approved_facts=facts or {},
        provenance={},
    )
    profile.id = uuid.uuid4()
    profile.created_at = now
    profile.updated_at = now
    return profile


def _mission(*, tenant_id: str) -> Mission:
    now = datetime(2026, 6, 3, tzinfo=UTC)
    mission = Mission(
        tenant_id=tenant_id,
        objective="Grow qualified pipeline",
        status="planned",
        compliance_category="operational",
        jurisdiction="US-ALL",
        metadata_json={},
    )
    mission.id = uuid.uuid4()
    mission.created_at = now
    mission.updated_at = now
    return mission


def _suggestion(*, tenant_id: str, category: str = "service_area") -> BusinessProfileSuggestion:
    suggestion = BusinessProfileSuggestion(
        tenant_id=tenant_id,
        suggested_category=category,
        suggested_fact={"value": "Dallas"},
        rationale="User stated this service area should be reused.",
        source_context={"conversation_id": "conv-1"},
    )
    suggestion.id = uuid.uuid4()
    suggestion.created_at = datetime(2026, 6, 3, tzinfo=UTC)
    return suggestion


def test_read_business_profile_returns_active_approved_facts_without_mutating() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    repo.add_profile(_profile(tenant_id=str(tenant_id), facts={"business_name": {"value": "Ajenda"}}))

    response = _client(tenant_id, repo).get("/v1/business-profile")

    assert response.status_code == 200
    assert response.json()["approved_facts"] == {"business_name": {"value": "Ajenda"}}
    assert len(repo.profiles) == 1
    assert repo.suggestions == {}


def test_explicit_profile_fact_upsert_creates_active_profile_truth() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()

    response = _client(tenant_id, repo).put(
        "/v1/business-profile/facts/business_name",
        json={"approved_fact": {"value": "Ajenda AI"}, "provenance_metadata": {"source": "onboarding"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == str(tenant_id)
    assert body["approved_facts"]["business_name"] == {"value": "Ajenda AI"}
    assert body["provenance"]["business_name"]["decision"] == "direct_update"
    assert body["provenance"]["business_name"]["metadata"] == {"source": "onboarding"}


def test_another_tenant_cannot_read_or_mutate_profile_or_suggestion() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    repo.add_profile(_profile(tenant_id=str(tenant_a), facts={"business_name": {"value": "Tenant A"}}))
    suggestion = repo.add_suggestion(_suggestion(tenant_id=str(tenant_a)))

    read_response = _client(tenant_b, repo).get("/v1/business-profile")
    approve_response = _client(tenant_b, repo).post(f"/v1/business-profile/suggestions/{suggestion.id}/approve")

    assert read_response.status_code == 200
    assert read_response.json()["approved_facts"] == {}
    assert approve_response.status_code == 404
    assert repo.profiles[str(tenant_a)].approved_facts == {"business_name": {"value": "Tenant A"}}


def test_pending_suggestion_does_not_alter_approved_facts_and_can_be_listed_by_status() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    repo.add_profile(_profile(tenant_id=str(tenant_id), facts={"service_area": {"value": "Austin"}}))

    create_response = _client(tenant_id, repo).post(
        "/v1/business-profile/suggestions",
        json={
            "suggested_category": "service_area",
            "suggested_fact": {"value": "Dallas"},
            "rationale": "User mentioned a possible reusable service area.",
            "source_context": {"conversation_id": "conv-1"},
        },
    )
    list_response = _client(tenant_id, repo).get("/v1/business-profile/suggestions?status=pending")

    assert create_response.status_code == 201
    assert create_response.json()["status"] == "pending"
    assert list_response.status_code == 200
    assert len(list_response.json()["suggestions"]) == 1
    assert repo.profiles[str(tenant_id)].approved_facts["service_area"] == {"value": "Austin"}


def test_suggestion_source_context_mission_id_is_validated_and_normalized() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    mission = _mission(tenant_id=str(tenant_id))

    response = _client(tenant_id, repo, missions={mission.id: mission}).post(
        "/v1/business-profile/suggestions",
        json={
            "suggested_category": "service_area",
            "suggested_fact": {"value": "Dallas"},
            "rationale": "User mentioned a reusable mission detail.",
            "source_context": {"mission_id": str(mission.id), "conversation_id": "conv-1"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["mission_id"] == str(mission.id)
    assert body["source_context"]["mission_id"] == str(mission.id)
    stored = next(iter(repo.suggestions.values()))
    assert stored.mission_id == mission.id


def test_suggestion_rejects_source_context_mission_id_not_visible_to_tenant() -> None:
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    mission = _mission(tenant_id=str(other_tenant_id))

    response = _client(tenant_id, repo, missions={mission.id: mission}).post(
        "/v1/business-profile/suggestions",
        json={
            "suggested_category": "service_area",
            "suggested_fact": {"value": "Dallas"},
            "rationale": "User mentioned a reusable mission detail.",
            "source_context": {"mission_id": str(mission.id), "conversation_id": "conv-1"},
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "business profile suggestion mission_id not found for tenant"}
    assert repo.suggestions == {}


def test_suggestion_rejects_invalid_source_context_mission_id() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()

    response = _client(tenant_id, repo).post(
        "/v1/business-profile/suggestions",
        json={
            "suggested_category": "service_area",
            "suggested_fact": {"value": "Dallas"},
            "rationale": "User mentioned a reusable mission detail.",
            "source_context": {"mission_id": "not-a-uuid", "conversation_id": "conv-1"},
        },
    )

    assert response.status_code == 422
    assert repo.suggestions == {}


def test_suggestion_rejects_mismatched_top_level_and_source_context_mission_ids() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    mission = _mission(tenant_id=str(tenant_id))

    response = _client(tenant_id, repo, missions={mission.id: mission}).post(
        "/v1/business-profile/suggestions",
        json={
            "mission_id": str(mission.id),
            "suggested_category": "service_area",
            "suggested_fact": {"value": "Dallas"},
            "rationale": "User mentioned a reusable mission detail.",
            "source_context": {"mission_id": str(uuid.uuid4()), "conversation_id": "conv-1"},
        },
    )

    assert response.status_code == 422
    assert repo.suggestions == {}


def test_approve_suggestion_as_is_promotes_suggested_fact_to_profile_truth() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    suggestion = repo.add_suggestion(_suggestion(tenant_id=str(tenant_id)))

    response = _client(tenant_id, repo).post(f"/v1/business-profile/suggestions/{suggestion.id}/approve")

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["approved_facts"]["service_area"] == {"value": "Dallas"}
    assert body["suggestion"]["status"] == "approved"
    assert body["suggestion"]["resolution"]["approved_fact"] == {"value": "Dallas"}


def test_approve_suggestion_with_edits_stores_edited_fact_not_original() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    suggestion = repo.add_suggestion(_suggestion(tenant_id=str(tenant_id)))

    response = _client(tenant_id, repo).post(
        f"/v1/business-profile/suggestions/{suggestion.id}/approve-with-edits",
        json={"approved_fact": {"value": "Fort Worth"}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["approved_facts"]["service_area"] == {"value": "Fort Worth"}
    assert body["profile"]["approved_facts"]["service_area"] != suggestion.suggested_fact
    assert body["suggestion"]["status"] == "edited"


def test_decline_suggestion_does_not_promote_profile_truth() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    profile = repo.add_profile(_profile(tenant_id=str(tenant_id)))
    suggestion = repo.add_suggestion(_suggestion(tenant_id=str(tenant_id)))

    response = _client(tenant_id, repo).post(f"/v1/business-profile/suggestions/{suggestion.id}/decline")

    assert response.status_code == 200
    assert response.json()["profile"] is None
    assert response.json()["suggestion"]["status"] == "declined"
    assert profile.approved_facts == {}


def test_dismiss_suggestion_does_not_promote_profile_truth() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    profile = repo.add_profile(_profile(tenant_id=str(tenant_id)))
    suggestion = repo.add_suggestion(_suggestion(tenant_id=str(tenant_id)))

    response = _client(tenant_id, repo).post(f"/v1/business-profile/suggestions/{suggestion.id}/dismiss")

    assert response.status_code == 200
    assert response.json()["profile"] is None
    assert response.json()["suggestion"]["status"] == "dismissed"
    assert profile.approved_facts == {}


def test_terminal_suggestions_cannot_be_resolved_twice() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    suggestion = repo.add_suggestion(_suggestion(tenant_id=str(tenant_id)))
    client = _client(tenant_id, repo)

    first_response = client.post(f"/v1/business-profile/suggestions/{suggestion.id}/decline")
    second_response = client.post(f"/v1/business-profile/suggestions/{suggestion.id}/approve")

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {"detail": "only pending business profile suggestions can be resolved"}
    assert repo.profiles == {}


def test_business_profile_routes_do_not_call_runtime_or_adjacent_contract_surfaces() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()

    with (
        patch("backend.services.mission_executor.MissionExecutor") as mission_executor,
        patch("backend.services.execution_coordinator.ExecutionCoordinator") as execution_coordinator,
        patch("backend.repositories.execution_task_repository.ExecutionTaskRepository") as execution_task_repository,
        patch("backend.repositories.worker_lease_repository.WorkerLeaseRepository") as worker_lease_repository,
        patch("backend.repositories.evidence_repository.EvidenceRepository") as evidence_repository,
        patch("backend.repositories.outcome_review_repository.OutcomeReviewRepository") as outcome_review_repository,
        patch("backend.repositories.retrieval_contract_repository.RetrievalContractRepository") as retrieval_repository,
    ):
        response = _client(tenant_id, repo).put(
            "/v1/business-profile/facts/evidence_expectations",
            json={"approved_fact": {"value": "Every result needs source evidence."}},
        )

    assert response.status_code == 200
    mission_executor.assert_not_called()
    execution_coordinator.assert_not_called()
    execution_task_repository.assert_not_called()
    worker_lease_repository.assert_not_called()
    evidence_repository.assert_not_called()
    outcome_review_repository.assert_not_called()
    retrieval_repository.assert_not_called()


def test_business_profile_routes_enforce_permissions() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()

    response = _client(tenant_id, repo, roles=("machine_executor",)).get("/v1/business-profile")

    assert response.status_code == 403
    assert response.json() == {"detail": "missing permission: business_profile:read"}
