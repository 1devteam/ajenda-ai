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
        "materialization_reference": {"materialization_id": "mat-1", "version": 1},
        "task_graph_reference": {"fingerprint": "graph-fp", "version": 2},
        "reviewed_success_criteria": [{"criterion_id": "c-1", "checked": True}],
        "evidence_references": [],
        "review_status": "in_review",
        "review_decision": "partial",
        "reviewer_type": "operator",
        "reviewer_source": "qa-reviewer",
        "review_summary": "Reviewed evidence against the mission success criteria.",
        "structured_findings": [{"criterion_id": "c-1", "result": "accepted"}],
        "confidence": 0.83,
        "trust_signal": {"method": "human-review", "calibrated": True},
        "unresolved_gaps": [{"criterion_id": "c-2", "reason": "missing artifact"}],
        "recommended_next_actions": [{"action": "collect_additional_artifact"}],
        "human_approval_required": True,
        "human_approval_status": "pending",
    }
    if evidence_id is not None:
        payload["evidence_references"] = [{"evidence_id": str(evidence_id), "role": "supporting"}]
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
    evidence_references = [] if evidence_id is None else [{"evidence_id": str(evidence_id), "role": "supporting"}]
    return SimpleNamespace(
        id=review_id or uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        materialization_reference={"materialization_id": "mat-1", "version": 1},
        task_graph_reference={"fingerprint": "graph-fp", "version": 2},
        reviewed_success_criteria=[{"criterion_id": "c-1", "checked": True}],
        evidence_references=evidence_references,
        review_status=review_status,
        review_decision="partial",
        reviewer_type="operator",
        reviewer_source="qa-reviewer",
        review_summary="Reviewed evidence against the mission success criteria.",
        structured_findings=[{"criterion_id": "c-1", "result": "accepted"}],
        confidence=0.83,
        trust_signal={"method": "human-review", "calibrated": True},
        unresolved_gaps=[{"criterion_id": "c-2", "reason": "missing artifact"}],
        recommended_next_actions=[{"action": "collect_additional_artifact"}],
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
    assert body["evidence_references"] == [{"evidence_id": str(evidence_id), "role": "supporting"}]
    review_repo.add.assert_called_once()
    created_record = review_repo.add.call_args.args[0]
    assert created_record.tenant_id == str(tenant_id)
    assert created_record.mission_id == mission_id
    assert created_record.schema_version == 1
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
    evidence_repo.get_for_tenant.assert_called_once_with(evidence_id=evidence_id, tenant_id=str(tenant_id))
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
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    review_repo = MagicMock()
    review_repo.list_for_mission.return_value = [_review_record(tenant_id=str(tenant_id), mission_id=mission_id)]

    with (
        patch("backend.api.routes.outcome_review.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
    ):
        response = client.get(f"/v1/outcome-reviews?mission_id={mission_id}")

    assert response.status_code == 200
    assert len(response.json()["outcome_reviews"]) == 1
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    review_repo.list_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_update_outcome_review_status_works() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    record = _review_record(tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id)
    review_repo = MagicMock()
    review_repo.get_for_tenant.return_value = record
    review_repo.update.side_effect = lambda review: review

    with patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo):
        response = client.patch(f"/v1/outcome-reviews/{review_id}", json={"review_status": "completed"})

    assert response.status_code == 200
    assert response.json()["review_status"] == "completed"
    assert record.review_status == "completed"
    review_repo.update.assert_called_once_with(record)


def test_explicit_null_patch_values_rejected_except_intentionally_nullable_fields() -> None:
    tenant_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(f"/v1/outcome-reviews/{review_id}", json={"review_status": None})

    assert response.status_code == 422
    assert "outcome review patch fields cannot be null: review_status" in response.text
