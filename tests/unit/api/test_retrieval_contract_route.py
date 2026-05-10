from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import retrieval_contract as retrieval_module
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session


def _build_app(tenant_id: uuid.UUID) -> FastAPI:
    app = FastAPI()
    app.include_router(retrieval_module.router, prefix="/v1")

    def _override_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_db() -> MagicMock:
        return MagicMock()

    app.dependency_overrides[get_request_tenant_id] = _override_tenant_id
    app.dependency_overrides[get_tenant_db_session] = _override_db
    return app


def _valid_payload(*, mission_id: uuid.UUID | None = None, memory_id: uuid.UUID | None = None) -> dict[str, object]:
    mission = mission_id or uuid.uuid4()
    memory = memory_id or uuid.uuid4()
    return {
        "mission_id": str(mission),
        "retrieval_request": {"query": "Find approved CRM onboarding learnings."},
        "retrieval_reason": "Need prior mission memory before planning the next step.",
        "retrieval_strategy": "hybrid",
        "strategy_metadata": {"declared_by": "operator"},
        "retrieval_filters": {"memory_type": "lesson"},
        "governance_constraints": {"jurisdiction": "US-ALL"},
        "memory_references": [{"memory_id": str(memory), "mission_id": str(mission)}],
        "returned_memory_references": [
            {"memory_id": str(memory), "mission_id": str(mission), "rank": 1, "reason": "policy match"}
        ],
        "confidence": 0.84,
        "trust_signal": {"source": "reviewed_outcome"},
        "provenance_metadata": {"requester": "unit-test"},
        "retrieval_status": "requested",
        "revocation_metadata": {},
    }


def _retrieval_record(
    *,
    tenant_id: str,
    mission_id: uuid.UUID,
    retrieval_id: uuid.UUID | None = None,
    retrieval_status: str = "requested",
) -> SimpleNamespace:
    now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    memory_id = uuid.uuid4()
    return SimpleNamespace(
        id=retrieval_id or uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=mission_id,
        retrieval_request={"query": "Find approved CRM onboarding learnings."},
        retrieval_reason="Need prior mission memory before planning the next step.",
        retrieval_strategy="hybrid",
        strategy_metadata={"declared_by": "operator"},
        retrieval_filters={"memory_type": "lesson"},
        governance_constraints={"jurisdiction": "US-ALL"},
        memory_references=[{"memory_id": str(memory_id), "mission_id": str(mission_id)}],
        returned_memory_references=[{"memory_id": str(memory_id), "mission_id": str(mission_id), "rank": 1}],
        confidence=0.84,
        trust_signal={"source": "reviewed_outcome"},
        provenance_metadata={"requester": "unit-test"},
        retrieval_status=retrieval_status,
        superseded_by_retrieval_id=None,
        revocation_metadata={},
        schema_version=1,
        created_at=now,
        updated_at=now,
    )


def test_retrieval_contract_creation_persists_tenant_owned_record_without_runtime_calls() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    retrieval_repo = MagicMock()
    retrieval_repo.add.return_value = _retrieval_record(tenant_id=str(tenant_id), mission_id=mission_id)

    with (
        patch("backend.api.routes.retrieval_contract.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.retrieval_contract.RetrievalContractRepository", return_value=retrieval_repo),
        patch("backend.services.mission_executor.MissionExecutor") as mission_executor,
        patch("backend.services.execution_coordinator.ExecutionCoordinator") as execution_coordinator,
    ):
        response = client.post("/v1/retrieval-contracts", json=_valid_payload(mission_id=mission_id))

    assert response.status_code == 201
    body = response.json()
    assert body["tenant_id"] == str(tenant_id)
    assert body["mission_id"] == str(mission_id)
    assert body["retrieval_strategy"] == "hybrid"
    created = retrieval_repo.add.call_args.args[0]
    assert created.tenant_id == str(tenant_id)
    assert created.mission_id == mission_id
    mission_executor.assert_not_called()
    execution_coordinator.assert_not_called()


def test_retrieval_contract_creation_rejects_foreign_mission() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = None
    retrieval_repo = MagicMock()

    with (
        patch("backend.api.routes.retrieval_contract.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.retrieval_contract.RetrievalContractRepository", return_value=retrieval_repo),
    ):
        response = client.post("/v1/retrieval-contracts", json=_valid_payload(mission_id=mission_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "mission not found for tenant"}
    retrieval_repo.add.assert_not_called()


def test_retrieval_contract_creation_rejects_foreign_memory_references() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    retrieval_repo = MagicMock()
    payload = _valid_payload(mission_id=mission_id)
    payload["memory_references"] = [{"memory_id": str(uuid.uuid4()), "tenant_id": str(uuid.uuid4())}]

    with (
        patch("backend.api.routes.retrieval_contract.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.retrieval_contract.RetrievalContractRepository", return_value=retrieval_repo),
    ):
        response = client.post("/v1/retrieval-contracts", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "memory_references are not owned by tenant mission"}
    retrieval_repo.add.assert_not_called()


def test_retrieval_contract_creation_rejects_foreign_returned_memory_references() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    retrieval_repo = MagicMock()
    payload = _valid_payload(mission_id=mission_id)
    payload["returned_memory_references"] = [{"memory_id": str(uuid.uuid4()), "mission_id": str(uuid.uuid4())}]

    with (
        patch("backend.api.routes.retrieval_contract.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.retrieval_contract.RetrievalContractRepository", return_value=retrieval_repo),
    ):
        response = client.post("/v1/retrieval-contracts", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": "returned_memory_references are not owned by tenant mission"}
    retrieval_repo.add.assert_not_called()


def test_read_retrieval_contract_hides_cross_tenant_record() -> None:
    tenant_id = uuid.uuid4()
    retrieval_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    retrieval_repo = MagicMock()
    retrieval_repo.get_for_tenant.return_value = None

    with patch("backend.api.routes.retrieval_contract.RetrievalContractRepository", return_value=retrieval_repo):
        response = client.get(f"/v1/retrieval-contracts/{retrieval_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "retrieval contract not found for tenant"}
    retrieval_repo.get_for_tenant.assert_called_once_with(retrieval_id=retrieval_id, tenant_id=str(tenant_id))


def test_list_retrieval_contracts_by_mission_is_tenant_scoped() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    mission_repo = MagicMock()
    mission_repo.get_for_tenant.return_value = SimpleNamespace(id=mission_id, tenant_id=str(tenant_id))
    retrieval_repo = MagicMock()
    retrieval_repo.list_for_mission.return_value = [_retrieval_record(tenant_id=str(tenant_id), mission_id=mission_id)]

    with (
        patch("backend.api.routes.retrieval_contract.MissionRepository", return_value=mission_repo),
        patch("backend.api.routes.retrieval_contract.RetrievalContractRepository", return_value=retrieval_repo),
    ):
        response = client.get(f"/v1/retrieval-contracts?mission_id={mission_id}")

    assert response.status_code == 200
    assert len(response.json()["retrieval_contracts"]) == 1
    mission_repo.get_for_tenant.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))
    retrieval_repo.list_for_mission.assert_called_once_with(mission_id=mission_id, tenant_id=str(tenant_id))


def test_update_retrieval_contract_status_works() -> None:
    tenant_id = uuid.uuid4()
    mission_id = uuid.uuid4()
    retrieval_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)
    record = _retrieval_record(tenant_id=str(tenant_id), mission_id=mission_id, retrieval_id=retrieval_id)
    retrieval_repo = MagicMock()
    retrieval_repo.get_for_tenant.return_value = record
    retrieval_repo.update.side_effect = lambda retrieval: retrieval

    with patch("backend.api.routes.retrieval_contract.RetrievalContractRepository", return_value=retrieval_repo):
        response = client.patch(f"/v1/retrieval-contracts/{retrieval_id}", json={"retrieval_status": "fulfilled"})

    assert response.status_code == 200
    assert response.json()["retrieval_status"] == "fulfilled"
    assert record.retrieval_status == "fulfilled"
    retrieval_repo.update.assert_called_once_with(record)


def test_explicit_null_patch_values_rejected_except_intentionally_nullable_fields() -> None:
    tenant_id = uuid.uuid4()
    retrieval_id = uuid.uuid4()
    app = _build_app(tenant_id)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(f"/v1/retrieval-contracts/{retrieval_id}", json={"retrieval_status": None})

    assert response.status_code == 422
    assert "retrieval contract patch fields cannot be null: retrieval_status" in response.text


def test_retrieval_contract_route_does_not_import_runtime_queue_or_search_execution_layers() -> None:
    route_source = retrieval_module.__file__
    assert route_source is not None
    source = open(route_source, encoding="utf-8").read()

    forbidden_terms = [
        "backend.queue",
        "TaskDispatcher",
        "MissionExecutor",
        "ExecutionCoordinator",
        "embedding",
        "vector",
        "semantic_rank",
    ]
    for forbidden_term in forbidden_terms:
        assert forbidden_term not in source
