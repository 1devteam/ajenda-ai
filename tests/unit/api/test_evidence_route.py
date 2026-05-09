from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import evidence as evidence_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(evidence_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def _valid_payload(
    *,
    mission_id: uuid.UUID | None = None,
    capability_id: uuid.UUID | None = None,
    adapter_id: uuid.UUID | None = None,
    execution_task_id: uuid.UUID | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "mission_id": str(mission_id or uuid.uuid4()),
        "task_graph_node_key": "research-node",
        "materialization_reference": {"metadata_key": "graph_materialization", "version": 1},
        "evidence_type": "artifact",
        "evidence_source": "capability-adapter",
        "summary": "Adapter produced an artifact proving the task output.",
        "structured_payload": {"record_count": 3},
        "artifact_references": [{"uri": "s3://tenant/artifact.json", "sha256": "abc"}],
        "provenance_metadata": {"collector": "unit-test"},
        "trust_signal": {"method": "checksum", "verified": True},
        "confidence": 0.91,
        "collection_status": "collected",
    }
    if capability_id is not None:
        payload["capability_id"] = str(capability_id)
    if adapter_id is not None:
        payload["capability_adapter_id"] = str(adapter_id)
    if execution_task_id is not None:
        payload["execution_task_id"] = str(execution_task_id)
    return payload


def _evidence_record(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    evidence_id: uuid.UUID | None = None,
    collection_status: str = "collected",
    capability_id: uuid.UUID | None = None,
    adapter_id: uuid.UUID | None = None,
    execution_task_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=evidence_id or uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        task_graph_node_key="research-node",
        materialization_reference={"metadata_key": "graph_materialization", "version": 1},
        execution_task_id=execution_task_id,
        capability_id=capability_id,
        capability_adapter_id=adapter_id,
        evidence_type="artifact",
        evidence_source="capability-adapter",
        summary="Adapter produced an artifact proving the task output.",
        structured_payload={"record_count": 3},
        artifact_references=[{"uri": "s3://tenant/artifact.json", "sha256": "abc"}],
        provenance_metadata={"collector": "unit-test"},
        trust_signal={"method": "checksum", "verified": True},
        confidence=0.91,
        collection_status=collection_status,
        schema_version=1,
        created_at=now,
        updated_at=now,
    )


def test_evidence_creation_persists_tenant_owned_record_without_runtime_calls() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    execution_task_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=capability_id, tenant_id=str(tenant_id), name="crm-record-review", version="1.0.0"
    )
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=adapter_id, tenant_id=str(tenant_id), capability_id=capability_id
    )
    task_repo = MagicMock()
    task_repo.get.return_value = SimpleNamespace(id=execution_task_id, tenant_id=str(tenant_id), mission_id=mission_id)
    evidence_repo = MagicMock()
    evidence_repo.add.return_value = _evidence_record(
        tenant_id=str(tenant_id),
        mission_id=mission_id,
        evidence_id=evidence_id,
        capability_id=capability_id,
        adapter_id=adapter_id,
        execution_task_id=execution_task_id,
    )

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.evidence.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.evidence.ExecutionTaskRepository", return_value=task_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
        patch("backend.api.routes.mission.ExecutionCoordinator") as coordinator_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
    ):
        response = client.post(
            "/v1/evidence",
            json=_valid_payload(
                mission_id=mission_id,
                capability_id=capability_id,
                adapter_id=adapter_id,
                execution_task_id=execution_task_id,
            ),
        )

    assert response.status_code == 201
    body = response.json()
    assert body["evidence_id"] == str(evidence_id)
    assert body["tenant_id"] == str(tenant_id)
    assert body["mission_id"] == str(mission_id)
    assert body["capability_id"] == str(capability_id)
    assert body["capability_adapter_id"] == str(adapter_id)
    created = evidence_repo.add.call_args.args[0]
    assert created.tenant_id == str(tenant_id)
    assert created.mission_id == mission_id
    assert created.evidence_type == "artifact"
    assert created.schema_version == 1
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    capability_repo.get_visible_for_tenant.assert_called_once_with(
        capability_id=capability_id, tenant_id=str(tenant_id)
    )
    adapter_repo.get_visible_for_tenant.assert_called_once_with(adapter_id=adapter_id, tenant_id=str(tenant_id))
    task_repo.get.assert_called_once_with(execution_task_id)
    coordinator_cls.assert_not_called()
    executor_cls.assert_not_called()


def test_evidence_creation_rejects_foreign_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = None
    evidence_repo = MagicMock()

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post("/v1/evidence", json=_valid_payload(mission_id=mission_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    evidence_repo.add.assert_not_called()


def test_evidence_read_hides_cross_tenant_record() -> None:
    tenant_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    evidence_repo = MagicMock()
    evidence_repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo):
        response = client.get(f"/v1/evidence/{evidence_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "evidence not found for tenant"}
    evidence_repo.get_for_tenant.assert_called_once_with(evidence_id=evidence_id, tenant_id=str(tenant_id))


def test_list_evidence_by_mission_is_tenant_scoped() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    evidence_repo = MagicMock()
    evidence_repo.list_for_mission.return_value = [_evidence_record(tenant_id=str(tenant_id), mission_id=mission_id)]

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.get(f"/v1/evidence?mission_id={mission_id}")

    assert response.status_code == 200
    assert len(response.json()["evidence"]) == 1
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    evidence_repo.list_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_evidence_creation_validates_capability_visibility() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = None
    evidence_repo = MagicMock()

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post("/v1/evidence", json=_valid_payload(mission_id=mission_id, capability_id=capability_id))

    assert response.status_code == 422
    assert response.json() == {"detail": "referenced capability is not visible to tenant"}
    evidence_repo.add.assert_not_called()


def test_evidence_creation_validates_adapter_visibility() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = None
    evidence_repo = MagicMock()

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post("/v1/evidence", json=_valid_payload(mission_id=mission_id, adapter_id=adapter_id))

    assert response.status_code == 422
    assert response.json() == {"detail": "referenced capability adapter is not visible to tenant"}
    evidence_repo.add.assert_not_called()


def test_evidence_creation_allows_capability_without_adapter_reference() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=capability_id, tenant_id=str(tenant_id), name="crm-record-review", version="1.0.0"
    )
    evidence_repo = MagicMock()
    evidence_repo.add.return_value = _evidence_record(
        tenant_id=str(tenant_id), mission_id=mission_id, capability_id=capability_id
    )

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post("/v1/evidence", json=_valid_payload(mission_id=mission_id, capability_id=capability_id))

    assert response.status_code == 201
    evidence_repo.add.assert_called_once()


def test_evidence_creation_allows_adapter_without_capability_reference() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=adapter_id, tenant_id=str(tenant_id), capability_id=uuid.uuid4()
    )
    evidence_repo = MagicMock()
    evidence_repo.add.return_value = _evidence_record(
        tenant_id=str(tenant_id), mission_id=mission_id, adapter_id=adapter_id
    )

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post("/v1/evidence", json=_valid_payload(mission_id=mission_id, adapter_id=adapter_id))

    assert response.status_code == 201
    evidence_repo.add.assert_called_once()


def test_evidence_creation_allows_adapter_bound_by_matching_capability_id() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=capability_id, tenant_id=str(tenant_id), name="crm-record-review", version="1.0.0"
    )
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=adapter_id, tenant_id=str(tenant_id), capability_id=capability_id
    )
    evidence_repo = MagicMock()
    evidence_repo.add.return_value = _evidence_record(
        tenant_id=str(tenant_id), mission_id=mission_id, capability_id=capability_id, adapter_id=adapter_id
    )

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.evidence.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post(
            "/v1/evidence",
            json=_valid_payload(mission_id=mission_id, capability_id=capability_id, adapter_id=adapter_id),
        )

    assert response.status_code == 201
    evidence_repo.add.assert_called_once()


def test_evidence_creation_rejects_adapter_bound_to_different_capability_id() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=capability_id, tenant_id=str(tenant_id), name="crm-record-review", version="1.0.0"
    )
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=adapter_id, tenant_id=str(tenant_id), capability_id=uuid.uuid4()
    )
    evidence_repo = MagicMock()

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.evidence.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post(
            "/v1/evidence",
            json=_valid_payload(mission_id=mission_id, capability_id=capability_id, adapter_id=adapter_id),
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "referenced capability adapter is not bound to capability"}
    evidence_repo.add.assert_not_called()


def test_evidence_creation_allows_adapter_bound_by_matching_capability_name_version() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=capability_id, tenant_id=str(tenant_id), name="crm-record-review", version="1.0.0"
    )
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=adapter_id,
        tenant_id=str(tenant_id),
        capability_id=None,
        capability_name="crm-record-review",
        capability_version="1.0.0",
    )
    evidence_repo = MagicMock()
    evidence_repo.add.return_value = _evidence_record(
        tenant_id=str(tenant_id), mission_id=mission_id, capability_id=capability_id, adapter_id=adapter_id
    )

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.evidence.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post(
            "/v1/evidence",
            json=_valid_payload(mission_id=mission_id, capability_id=capability_id, adapter_id=adapter_id),
        )

    assert response.status_code == 201
    evidence_repo.add.assert_called_once()


def test_evidence_creation_rejects_adapter_bound_to_different_capability_name_version() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    capability_id = uuid.uuid4()
    adapter_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    capability_repo = MagicMock()
    capability_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=capability_id, tenant_id=str(tenant_id), name="crm-record-review", version="1.0.0"
    )
    adapter_repo = MagicMock()
    adapter_repo.get_visible_for_tenant.return_value = SimpleNamespace(
        id=adapter_id,
        tenant_id=str(tenant_id),
        capability_id=None,
        capability_name="crm-record-review",
        capability_version="2.0.0",
    )
    evidence_repo = MagicMock()

    with (
        patch("backend.api.routes.evidence.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.evidence.CapabilityRepository", return_value=capability_repo),
        patch("backend.api.routes.evidence.CapabilityAdapterRepository", return_value=adapter_repo),
        patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo),
    ):
        response = client.post(
            "/v1/evidence",
            json=_valid_payload(mission_id=mission_id, capability_id=capability_id, adapter_id=adapter_id),
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "referenced capability adapter is not bound to capability"}
    evidence_repo.add.assert_not_called()


def test_update_evidence_status_and_metadata_works() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    evidence = _evidence_record(tenant_id=str(tenant_id), mission_id=mission_id, evidence_id=evidence_id)
    updated = _evidence_record(
        tenant_id=str(tenant_id), mission_id=mission_id, evidence_id=evidence_id, collection_status="verified"
    )
    updated.provenance_metadata = {"reviewer": "ops"}
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    evidence_repo = MagicMock()
    evidence_repo.get_for_tenant.return_value = evidence
    evidence_repo.update.return_value = updated

    with patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo):
        response = client.patch(
            f"/v1/evidence/{evidence_id}",
            json={"collection_status": "verified", "provenance_metadata": {"reviewer": "ops"}},
        )

    assert response.status_code == 200
    assert response.json()["collection_status"] == "verified"
    assert evidence.collection_status == "verified"
    assert evidence.provenance_metadata == {"reviewer": "ops"}
    evidence_repo.update.assert_called_once_with(evidence)


def test_update_evidence_allows_clearing_nullable_confidence() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    evidence = _evidence_record(tenant_id=str(tenant_id), mission_id=mission_id, evidence_id=evidence_id)
    evidence.confidence = 0.91
    updated = _evidence_record(tenant_id=str(tenant_id), mission_id=mission_id, evidence_id=evidence_id)
    updated.confidence = None
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    evidence_repo = MagicMock()
    evidence_repo.get_for_tenant.return_value = evidence
    evidence_repo.update.return_value = updated

    with patch("backend.api.routes.evidence.EvidenceRepository", return_value=evidence_repo):
        response = client.patch(f"/v1/evidence/{evidence_id}", json={"confidence": None})

    assert response.status_code == 200
    assert response.json()["confidence"] is None
    assert evidence.confidence is None
    evidence_repo.update.assert_called_once_with(evidence)


def test_evidence_patch_rejects_explicit_null_collection_status() -> None:
    tenant_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(f"/v1/evidence/{evidence_id}", json={"collection_status": None})

    assert response.status_code == 422
    assert "cannot be null" in response.text
