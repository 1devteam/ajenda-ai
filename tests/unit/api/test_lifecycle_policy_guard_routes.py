from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.routes import evidence as evidence_module
from backend.api.routes import outcome_review as outcome_review_module
from backend.app.config import Settings
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.auth.principal import Principal, PrincipalType


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

    app.include_router(evidence_module.router, prefix="/v1")
    app.include_router(outcome_review_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def _lifecycle_floor_settings() -> SimpleNamespace:
    return SimpleNamespace(
        lifecycle_policy_enforce_retention_class=False,
        lifecycle_policy_enforce_escalation_transitions=False,
        lifecycle_policy_enforce_provenance_confidence_floor=True,
        lifecycle_policy_provenance_confidence_floor=0.75,
    )


def _evidence_payload(*, mission_id: uuid.UUID, confidence: float | None = 0.91) -> dict[str, object]:
    return {
        "mission_id": str(mission_id),
        "task_graph_node_key": "research-node",
        "materialization_reference": {"metadata_key": "graph_materialization", "version": 1},
        "evidence_type": "artifact",
        "evidence_source": "capability-adapter",
        "summary": "Adapter produced an artifact proving the task output.",
        "structured_payload": {"record_count": 3},
        "artifact_references": [{"uri": "s3://tenant/artifact.json", "sha256": "abc"}],
        "provenance_metadata": {"collector": "unit-test", "retention_class": "standard"},
        "trust_signal": {"method": "checksum", "verified": True},
        "confidence": confidence,
        "collection_status": "collected",
    }


def _outcome_review_payload(*, mission_id: uuid.UUID, confidence: float | None = 0.83) -> dict[str, object]:
    return {
        "mission_id": str(mission_id),
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
        "confidence": confidence,
        "trust_signal": {"method": "human-review", "calibrated": True},
        "unresolved_gaps": [{"criterion_id": "c-2", "reason": "missing artifact"}],
        "recommended_next_actions": [{"action": "collect_additional_artifact"}],
        "human_approval_required": True,
        "human_approval_status": "pending",
    }


def _review_record(*, tenant_id: str, mission_id: uuid.UUID, review_id: uuid.UUID) -> SimpleNamespace:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=review_id,
        tenant_id=tenant_id,
        mission_id=mission_id,
        materialization_reference={"materialization_id": "mat-1", "version": 1},
        task_graph_reference={"fingerprint": "graph-fp", "version": 2},
        reviewed_success_criteria=[{"criterion_id": "c-1", "checked": True}],
        evidence_references=[],
        review_status="in_review",
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


@pytest.mark.parametrize("retention_class", [None, "", "   "])
def test_evidence_create_requires_non_empty_retention_class_when_enabled(retention_class: object) -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    payload = _evidence_payload(mission_id=mission_id)
    payload["provenance_metadata"] = {"collector": "unit-test", "retention_class": retention_class}

    settings = SimpleNamespace(
        lifecycle_policy_enforce_retention_class=True,
        lifecycle_policy_enforce_escalation_transitions=False,
        lifecycle_policy_enforce_provenance_confidence_floor=False,
        lifecycle_policy_provenance_confidence_floor=0.75,
    )
    with (
        patch("backend.api.routes.evidence.get_settings", return_value=settings),
        patch("backend.api.routes.evidence.MissionRepository") as mission_repo_cls,
        patch("backend.api.routes.evidence.EvidenceRepository") as evidence_repo_cls,
    ):
        response = client.post("/v1/evidence", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "retention_class is required by lifecycle policy"}
    mission_repo_cls.assert_not_called()
    evidence_repo_cls.assert_not_called()


def test_evidence_create_blocks_below_confidence_floor_before_persistence() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with (
        patch("backend.api.routes.evidence.get_settings", return_value=_lifecycle_floor_settings()),
        patch("backend.api.routes.evidence.MissionRepository") as mission_repo_cls,
        patch("backend.api.routes.evidence.EvidenceRepository") as evidence_repo_cls,
    ):
        response = client.post("/v1/evidence", json=_evidence_payload(mission_id=mission_id, confidence=0.5))

    assert response.status_code == 422
    assert response.json() == {"detail": "confidence is below lifecycle policy floor (0.75)"}
    mission_repo_cls.assert_not_called()
    evidence_repo_cls.assert_not_called()


@pytest.mark.parametrize("confidence", [None])
def test_evidence_create_requires_confidence_when_floor_enabled(confidence: None) -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with (
        patch("backend.api.routes.evidence.get_settings", return_value=_lifecycle_floor_settings()),
        patch("backend.api.routes.evidence.MissionRepository") as mission_repo_cls,
        patch("backend.api.routes.evidence.EvidenceRepository") as evidence_repo_cls,
    ):
        response = client.post("/v1/evidence", json=_evidence_payload(mission_id=mission_id, confidence=confidence))

    assert response.status_code == 422
    assert response.json() == {"detail": "confidence is required by lifecycle policy"}
    mission_repo_cls.assert_not_called()
    evidence_repo_cls.assert_not_called()


def test_outcome_review_create_blocks_below_confidence_floor_before_persistence() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with (
        patch("backend.api.routes.outcome_review.get_settings", return_value=_lifecycle_floor_settings()),
        patch("backend.api.routes.outcome_review.MissionRepository") as mission_repo_cls,
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository") as review_repo_cls,
    ):
        response = client.post(
            "/v1/outcome-reviews", json=_outcome_review_payload(mission_id=mission_id, confidence=0.5)
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "confidence is below lifecycle policy floor (0.75)"}
    mission_repo_cls.assert_not_called()
    review_repo_cls.assert_not_called()


def test_outcome_review_create_requires_confidence_when_floor_enabled() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    with (
        patch("backend.api.routes.outcome_review.get_settings", return_value=_lifecycle_floor_settings()),
        patch("backend.api.routes.outcome_review.MissionRepository") as mission_repo_cls,
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository") as review_repo_cls,
    ):
        response = client.post(
            "/v1/outcome-reviews", json=_outcome_review_payload(mission_id=mission_id, confidence=None)
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "confidence is required by lifecycle policy"}
    mission_repo_cls.assert_not_called()
    review_repo_cls.assert_not_called()


def test_outcome_review_update_blocks_below_confidence_floor_before_persistence() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    review_repo = MagicMock()
    review_repo.get_for_tenant.return_value = _review_record(
        tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id
    )

    with (
        patch("backend.api.routes.outcome_review.get_settings", return_value=_lifecycle_floor_settings()),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
    ):
        response = client.patch(f"/v1/outcome-reviews/{review_id}", json={"confidence": 0.5})

    assert response.status_code == 422
    assert response.json() == {"detail": "confidence is below lifecycle policy floor (0.75)"}
    review_repo.get_for_tenant.assert_called_once_with(review_id=review_id, tenant_id=str(tenant_id))
    review_repo.update.assert_not_called()


def test_outcome_review_update_requires_confidence_when_floor_enabled() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    review_repo = MagicMock()
    review_repo.get_for_tenant.return_value = _review_record(
        tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id
    )

    with (
        patch("backend.api.routes.outcome_review.get_settings", return_value=_lifecycle_floor_settings()),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
    ):
        response = client.patch(f"/v1/outcome-reviews/{review_id}", json={"confidence": None})

    assert response.status_code == 422
    assert response.json() == {"detail": "confidence is required by lifecycle policy"}
    review_repo.get_for_tenant.assert_called_once_with(review_id=review_id, tenant_id=str(tenant_id))
    review_repo.update.assert_not_called()


def test_evidence_create_allows_missing_retention_and_confidence_when_policy_flags_disabled() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    evidence_repo = MagicMock()
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    evidence_repo.add.return_value = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        task_graph_node_key="research-node",
        materialization_reference={"metadata_key": "graph_materialization", "version": 1},
        execution_task_id=None,
        capability_id=None,
        capability_adapter_id=None,
        evidence_type="artifact",
        evidence_source="capability-adapter",
        summary="Adapter produced an artifact proving the task output.",
        structured_payload={"record_count": 3},
        artifact_references=[{"uri": "s3://tenant/artifact.json", "sha256": "abc"}],
        provenance_metadata={"collector": "unit-test"},
        trust_signal={"method": "checksum", "verified": True},
        confidence=None,
        collection_status="collected",
        schema_version=1,
        created_at=now,
        updated_at=now,
    )

    permissive_settings = SimpleNamespace(
        lifecycle_policy_enforce_retention_class=False,
        lifecycle_policy_enforce_escalation_transitions=False,
        lifecycle_policy_enforce_provenance_confidence_floor=False,
        lifecycle_policy_provenance_confidence_floor=0.75,
    )

    payload = _evidence_payload(mission_id=mission_id, confidence=None)
    payload["provenance_metadata"] = {"collector": "unit-test"}

    with (
        patch("backend.api.routes.evidence.get_settings", return_value=permissive_settings),
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post("/v1/evidence", json=payload)

    assert response.status_code == 201
    assert response.json()["confidence"] is None
    assert response.json()["provenance_metadata"] == {"collector": "unit-test"}
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    evidence_repo.add.assert_called_once()


def test_outcome_review_create_allows_escalated_without_confidence_when_policy_flags_disabled() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    review_repo = MagicMock()
    review_id = uuid.uuid4()
    review_repo.add.return_value = _review_record(tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id)
    review_repo.add.return_value.review_status = "escalated"
    review_repo.add.return_value.confidence = None

    permissive_settings = SimpleNamespace(
        lifecycle_policy_enforce_retention_class=False,
        lifecycle_policy_enforce_escalation_transitions=False,
        lifecycle_policy_enforce_provenance_confidence_floor=False,
        lifecycle_policy_provenance_confidence_floor=0.75,
    )

    payload = _outcome_review_payload(mission_id=mission_id, confidence=None)
    payload["review_status"] = "escalated"

    with (
        patch("backend.api.routes.outcome_review.get_settings", return_value=permissive_settings),
        patch("backend.api.routes.outcome_review.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
        patch("backend.api.routes.outcome_review.EvidenceRepository") as evidence_repo_cls,
    ):
        evidence_repo_cls.return_value.get_for_tenant.return_value = None
        response = client.post("/v1/outcome-reviews", json=payload)

    assert response.status_code == 201
    assert response.json()["review_status"] == "escalated"
    assert response.json()["confidence"] is None
    review_repo.add.assert_called_once()


def test_outcome_review_update_allows_invalid_transition_when_enforcement_disabled() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    review_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    review_repo = MagicMock()
    review = _review_record(tenant_id=str(tenant_id), mission_id=mission_id, review_id=review_id)
    review.review_status = "draft"
    review_repo.get_for_tenant.return_value = review
    review_repo.update.side_effect = lambda updated: updated

    permissive_settings = SimpleNamespace(
        lifecycle_policy_enforce_retention_class=False,
        lifecycle_policy_enforce_escalation_transitions=False,
        lifecycle_policy_enforce_provenance_confidence_floor=False,
        lifecycle_policy_provenance_confidence_floor=0.75,
    )

    with (
        patch("backend.api.routes.outcome_review.get_settings", return_value=permissive_settings),
        patch("backend.api.routes.outcome_review.OutcomeReviewRepository", return_value=review_repo),
    ):
        response = client.patch(f"/v1/outcome-reviews/{review_id}", json={"review_status": "completed"})

    assert response.status_code == 200
    assert response.json()["review_status"] == "completed"
    review_repo.update.assert_called_once_with(review)


def _settings_with_confidence_floor(value: float) -> Settings:
    return Settings.model_construct(
        app_name="Ajenda AI",
        env="production",
        log_level="INFO",
        log_json=True,
        host="0.0.0.0",
        port=8000,
        database_url="postgresql+psycopg://ajenda:ajenda@db:5432/ajenda",
        db_pool_size=10,
        db_max_overflow=20,
        db_pool_timeout=30,
        db_pool_recycle=1800,
        redact_keys="password,secret",
        queue_adapter="redis",
        queue_url="redis://redis:6379/0",
        worker_poll_interval_seconds=2.0,
        worker_identity="worker-1",
        worker_tenant_id="00000000-0000-0000-0000-000000000001",
        oidc_jwks_uri="https://idp.example.com/realms/ajenda/protocol/openid-connect/certs",
        oidc_issuer="https://idp.example.com/realms/ajenda",
        oidc_audience="ajenda-api",
        rate_limit_requests=100,
        rate_limit_window_seconds=60,
        authz_policy_mode="rbac",
        authz_opa_url=None,
        authz_opa_timeout_seconds=2.0,
        webhook_secret_encryption_key=Fernet.generate_key().decode(),
        webhook_secret_encryption_key_prev=None,
        runtime_secret_encryption_key=Fernet.generate_key().decode(),
        runtime_secret_encryption_key_prev=None,
        lifecycle_policy_enforce_retention_class=False,
        lifecycle_policy_enforce_escalation_transitions=False,
        lifecycle_policy_enforce_provenance_confidence_floor=False,
        lifecycle_policy_provenance_confidence_floor=value,
    )


@pytest.mark.parametrize("floor", [-0.01, 1.01, float("nan")])
def test_lifecycle_confidence_floor_config_must_be_between_zero_and_one(floor: float) -> None:
    settings = _settings_with_confidence_floor(floor)

    with pytest.raises(ValueError, match="AJENDA_LIFECYCLE_POLICY_PROVENANCE_CONFIDENCE_FLOOR"):
        settings.validate_runtime_contract()


def test_lifecycle_confidence_floor_config_accepts_bounds() -> None:
    _settings_with_confidence_floor(0).validate_runtime_contract()
    _settings_with_confidence_floor(1).validate_runtime_contract()
