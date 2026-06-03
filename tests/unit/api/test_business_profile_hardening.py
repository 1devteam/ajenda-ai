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


class _FakeBusinessProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[str, BusinessProfile] = {}
        self.suggestions: dict[uuid.UUID, BusinessProfileSuggestion] = {}

    def add_profile(self, profile: BusinessProfile) -> BusinessProfile:
        profile.id = profile.id or uuid.uuid4()
        profile.created_at = profile.created_at or datetime(2026, 6, 3, tzinfo=UTC)
        profile.updated_at = profile.updated_at or profile.created_at
        self.profiles[profile.tenant_id] = profile
        return profile

    def get_or_create_active_profile(self, *, tenant_id: str, schema_version: int) -> BusinessProfile:
        profile = self.get_active_profile_for_tenant(tenant_id=tenant_id)
        if profile is not None:
            return profile
        return self.add_profile(
            BusinessProfile(tenant_id=tenant_id, approved_facts={}, provenance={}, schema_version=schema_version)
        )

    def get_active_profile_for_tenant(self, *, tenant_id: str) -> BusinessProfile | None:
        profile = self.profiles.get(tenant_id)
        if profile and profile.status == "active":
            return profile
        return None

    def upsert_approved_fact(self, **kwargs: object) -> BusinessProfile:
        from backend.repositories.business_profile_repository import BusinessProfileRepository

        return BusinessProfileRepository(MagicMock()).upsert_approved_fact(**kwargs)  # type: ignore[arg-type]

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


def _client(tenant_id: uuid.UUID, repo: _FakeBusinessProfileRepository, db: MagicMock | None = None) -> TestClient:
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

    app.include_router(business_profile_module.router, prefix="/v1")
    app.dependency_overrides[get_request_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_tenant_db_session] = lambda: db or MagicMock()
    business_profile_module.BusinessProfileRepository = lambda _db: repo  # type: ignore[assignment]
    return TestClient(app, raise_server_exceptions=False)


def _profile(*, tenant_id: str) -> BusinessProfile:
    profile = BusinessProfile(tenant_id=tenant_id, approved_facts={}, provenance={})
    profile.id = uuid.uuid4()
    profile.created_at = datetime(2026, 6, 3, tzinfo=UTC)
    profile.updated_at = profile.created_at
    return profile


def test_history_read_surface_exposes_supersession_and_suggestion_decisions() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    profile = repo.add_profile(_profile(tenant_id=str(tenant_id)))
    profile.approved_facts = {"service_area": {"value": "Dallas"}}
    profile.provenance = {
        "service_area": {
            "actor_id": "test-user",
            "decision": "direct_update",
            "updated_at": "2026-06-03T00:00:00+00:00",
            "superseded_fact": {"value": "Austin"},
        }
    }
    suggestion = BusinessProfileSuggestion(
        tenant_id=str(tenant_id),
        profile_id=profile.id,
        suggested_category="service_area",
        suggested_fact={"value": "Fort Worth"},
        rationale="Reusable service area.",
        source_context={"conversation_id": "conv-1"},
        status="declined",
        resolution={"actor_id": "test-user", "decision": "declined"},
        resolved_at=datetime(2026, 6, 3, tzinfo=UTC),
    )
    repo.add_suggestion(suggestion)

    response = _client(tenant_id, repo).get("/v1/business-profile/history")

    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["approved_facts"] == {"service_area": {"value": "Dallas"}}
    assert {entry["entry_type"] for entry in body["entries"]} == {"profile_fact", "suggestion_decision"}
    assert body["entries"][0]["superseded_fact"] == {"value": "Austin"}
    assert body["suggestions"][0]["status"] == "declined"


def test_fact_upsert_normalizes_category_and_rejects_oversized_json() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    client = _client(tenant_id, repo)

    ok = client.put("/v1/business-profile/facts/ Service_Area ", json={"approved_fact": {"value": "Dallas"}})
    too_large = client.put(
        "/v1/business-profile/facts/service_area",
        json={"approved_fact": {"value": "x" * (business_profile_module.MAX_PROFILE_JSON_BYTES + 1)}},
    )

    assert ok.status_code == 200
    assert "service_area" in ok.json()["approved_facts"]
    assert too_large.status_code == 422


def test_suggestion_mission_id_must_be_tenant_owned_and_consistent_with_source_context() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    mission_id = uuid.uuid4()
    other_mission_id = uuid.uuid4()
    db = MagicMock()
    client = _client(tenant_id, repo, db=db)

    with patch.object(business_profile_module.MissionRepository, "get_for_tenant", return_value=None) as get_for_tenant:
        missing = client.post(
            "/v1/business-profile/suggestions",
            json={
                "suggested_category": "service_area",
                "suggested_fact": {"value": "Dallas"},
                "rationale": "Mission context may be reusable.",
                "mission_id": str(mission_id),
                "source_context": {"mission_id": str(mission_id)},
            },
        )

    inconsistent = client.post(
        "/v1/business-profile/suggestions",
        json={
            "suggested_category": "service_area",
            "suggested_fact": {"value": "Dallas"},
            "rationale": "Mission context may be reusable.",
            "mission_id": str(mission_id),
            "source_context": {"mission_id": str(other_mission_id)},
        },
    )

    assert missing.status_code == 404
    get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    assert inconsistent.status_code == 422


def test_suggestion_source_context_mission_id_is_promoted_to_first_class_link() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    mission_id = uuid.uuid4()
    db = MagicMock()

    with patch.object(
        business_profile_module.MissionRepository, "get_for_tenant", return_value=object()
    ) as get_for_tenant:
        response = _client(tenant_id, repo, db=db).post(
            "/v1/business-profile/suggestions",
            json={
                "suggested_category": "service_area",
                "suggested_fact": {"value": "Dallas"},
                "rationale": "Mission context may be reusable.",
                "source_context": {"mission_id": str(mission_id), "conversation_id": "conv-1"},
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["mission_id"] == str(mission_id)
    assert body["source_context"]["mission_id"] == str(mission_id)
    suggestion = next(iter(repo.suggestions.values()))
    assert suggestion.mission_id == mission_id
    get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_profile_mutations_append_business_profile_audit_event() -> None:
    tenant_id = uuid.uuid4()
    repo = _FakeBusinessProfileRepository()
    db = MagicMock()

    response = _client(tenant_id, repo, db=db).put(
        "/v1/business-profile/facts/business_name",
        json={"approved_fact": {"value": "Ajenda AI"}},
    )

    assert response.status_code == 200
    audit_event = db.add.call_args.args[0]
    assert audit_event.tenant_id == str(tenant_id)
    assert audit_event.category == "business_profile"
    assert audit_event.action == "business_profile_fact_upserted"
    assert audit_event.payload_json["runtime_side_effects"] is False
