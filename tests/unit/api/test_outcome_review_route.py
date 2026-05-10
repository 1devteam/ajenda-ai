from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import outcome_review as outcome_review_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(outcome_review_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def _valid_payload(*, mission_id: uuid.UUID | None = None, evidence_id: uuid.UUID | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "mission_id": str(mission_id or uuid.uuid4()),
        "outcome_ref": {"claim": "Mission objective satisfied", "source": "operator"},
        "materialization_reference": {"metadata_key": "graph_materialization", "version": 1},
        "task_graph_reference": {"graph_fingerprint": "abc123", "graph_version": 1},
        "reviewed_success_criteria": [{"key": "delivered", "result": "accepted"}],
        "evidence_references": [],
        "review_status": "in_review",
        "review_decision": "partial",
        "reviewer_type": "operator",
        "reviewer_source": "ops-console",
        "review_summary": "Outcome is partially supported by evidence.",
        "structured_findings": [{"criterion": "delivered", "finding": "artifact exists"}],
        "confidence": 0.82,
        "trust_signal": {"basis": "verified-evidence"},
        "unresolved_gaps": [{"gap": "approval pending"}],
        "recommended_next_actions": [{"action": "request approval"}],
        "human_approval_required": True,
        "human_approval_status": "pending",
    }
    if evidence_id is not None:
        payload["evidence_references"] = [
            {"evidence_id": str(evidence_id), "relationship": "supports", "success_criteria_keys": ["delivered"]}
        ]
    return payload


def _review_record(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    review_id: uuid.UUID | None = None,
    evidence_id: uuid.UUID | None = None,
    review_status: str = "in_review",
) -> SimpleNamespace:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=review_id or uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        outcome_ref={"claim": "Mission objective satisfied", "source": "operator"},
        materialization_reference={"metadata_key": "graph_materialization", "version": 1},
        task_graph_reference={"graph_fingerprint": "abc123", "graph_version": 1},
        reviewed_success_criteria=[{"key": "delivered", "result": "accepted"}],
        evidence_references=[]
        if evidence_id is None
        else [{"evidence_id": str(evidence_id), "relationship": "supports", "success_criteria_keys": ["delivered"]}],
        review_status=review_status,
        review_decision="partial",
        reviewer_type="operator",
        reviewer_source="ops-console",
        review_summary="Outcome is partially supported by evidence.",
        structured_findings=[{"criterion": "delivered", "finding": "artifact exists"}],
        confidence=0.82,
        trust_signal={"basis": "verified-evidence"},
        unresolved_gaps=[{"gap": "approval pending"}],
        recommended_next_actions=[{"action": "request approval"}],
        human_approval_required=True,
        human_approval_status="pending",
        schema_version=1,
        created_at=now,
        updated_at=now,
    )


def test_outcome_review_creation_persists_tenant_owned_record_without_runtime_calls() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    evidence_repo = MagicMock()
    evidence_repo.get_for_tenant.return_value = SimpleNamespace(
        id=evidence_id, tenant_id=str(tenant_id), mission_id=mission_id
    )
    review_repo = MagicMock()
    review_repo.add.return_value = _review_record(
        tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id, evidence_id=evidence_id
    )

    with (
        patch("backend.api.routes.outcome_review.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.outcome_review.EvidenceRepository", return_value=evidence_repo),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
    ):
        response = client.post(
            "/v1/outcome-reviews", json=_valid_payload(mission_id=mission_id, evidence_id=evidence_id)
        )

    assert response.status_code == 201
    body = response.json()
    assert body["review_id"] == str(review_id)
    assert body["tenant_id"] == str(tenant_id)
    assert body["mission_id"] == str(mission_id)
    assert body["evidence_references"][0]["evidence_id"] == str(evidence_id)
    created_review = review_repo.add.call_args.args[0]
    assert created_review.tenant_id == str(tenant_id)
    assert created_review.mission_id == mission_id
    assert created_review.schema_version == 1
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()


def test_outcome_review_creation_rejects_foreign_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = None
    review_repo = MagicMock()

    with (
        patch("backend.api.routes.outcome_review.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
    ):
        response = client.post("/v1/outcome-reviews", json=_valid_payload(mission_id=mission_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    review_repo.add.assert_not_called()


def test_outcome_review_creation_rejects_evidence_from_another_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    evidence_repo = MagicMock()
    evidence_repo.get_for_tenant.return_value = SimpleNamespace(
        id=evidence_id, tenant_id=str(tenant_id), mission_id=uuid.uuid4()
    )
    review_repo = MagicMock()

    with (
        patch("backend.api.routes.outcome_review.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.outcome_review.EvidenceRepository", return_value=evidence_repo),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
    ):
        response = client.post(
            "/v1/outcome-reviews", json=_valid_payload(mission_id=mission_id, evidence_id=evidence_id)
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "referenced evidence is not owned by tenant mission"}
    review_repo.add.assert_not_called()


def test_outcome_review_creation_rejects_evidence_from_another_tenant() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    evidence_repo = MagicMock()
    evidence_repo.get_for_tenant.return_value = None
    review_repo = MagicMock()

    with (
        patch("backend.api.routes.outcome_review.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.outcome_review.EvidenceRepository", return_value=evidence_repo),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
    ):
        response = client.post(
            "/v1/outcome-reviews", json=_valid_payload(mission_id=mission_id, evidence_id=evidence_id)
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "referenced evidence is not owned by tenant mission"}
    review_repo.add.assert_not_called()


def test_read_outcome_review_hides_cross_tenant_record() -> None:
    tenant_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    review_repo = MagicMock()
    review_repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo):
        response = client.get(f"/v1/outcome-reviews/{review_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "outcome review not found for tenant"}
    review_repo.get_for_tenant.assert_called_once_with(review_id=review_id, tenant_id=str(tenant_id))


def test_list_outcome_reviews_by_mission_is_tenant_scoped() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    review_repo = MagicMock()
    review_repo.list_for_mission.return_value = [
        _review_record(tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id)
    ]

    with (
        patch("backend.api.routes.outcome_review.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
    ):
        response = client.get(f"/v1/outcome-reviews?mission_id={mission_id}")

    assert response.status_code == 200
    body = response.json()
    assert [review["review_id"] for review in body["outcome_reviews"]] == [str(review_id)]
    review_repo.list_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_update_outcome_review_status_works() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    review_id = uuid.uuid4()
    review = _review_record(tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id)
    updated = _review_record(
        tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id, review_status="completed"
    )
    updated.review_decision = "accepted"
    updated.human_approval_required = True
    updated.human_approval_status = "approved"
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    review_repo = MagicMock()
    review_repo.get_for_tenant.return_value = review
    review_repo.update.return_value = updated

    with patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo):
        response = client.patch(
            f"/v1/outcome-reviews/{review_id}",
            json={"review_status": "completed", "review_decision": "accepted", "human_approval_status": "approved"},
        )

    assert response.status_code == 200
    assert response.json()["review_status"] == "completed"
    assert review.review_status == "completed"
    assert review.review_decision == "accepted"
    review_repo.update.assert_called_once_with(review)


def test_outcome_review_patch_rejects_explicit_null_status() -> None:
    tenant_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(f"/v1/outcome-reviews/{review_id}", json={"review_status": None})

    assert response.status_code == 422
    assert "cannot be null" in response.text


def test_outcome_review_patch_allows_clearing_nullable_confidence() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    review_id = uuid.uuid4()
    review = _review_record(tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id)
    review.confidence = 0.82
    updated = _review_record(tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id)
    updated.confidence = None
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    review_repo = MagicMock()
    review_repo.get_for_tenant.return_value = review
    review_repo.update.return_value = updated

    with patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo):
        response = client.patch(f"/v1/outcome-reviews/{review_id}", json={"confidence": None})

    assert response.status_code == 200
    assert response.json()["confidence"] is None
    assert review.confidence is None
    review_repo.update.assert_called_once_with(review)
