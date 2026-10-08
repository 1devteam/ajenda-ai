from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routes import mission_runtime as mission_module
from backend.services.worker_claim_admission_service import WorkerClaimAdmissionService
from backend.services.worker_run_admission_service import WorkerRunAdmissionService
from backend.services.worker_start_admission_service import WorkerStartAdmissionService


@pytest.mark.parametrize(
    "service",
    [
        WorkerClaimAdmissionService(MagicMock()),
        WorkerStartAdmissionService(MagicMock()),
    ],
)
def test_http_claim_and_start_services_are_fail_closed_tombstones(service: object) -> None:
    with pytest.raises(HTTPException, match="daemon worker runtime") as exc_info:
        service.admit(  # type: ignore[attr-defined]
            mission_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            admitted_by="test",
        )
    assert exc_info.value.status_code == 410


def test_http_run_service_is_fail_closed_tombstone() -> None:
    service = WorkerRunAdmissionService(MagicMock(), MagicMock())
    with pytest.raises(HTTPException, match="daemon worker runtime") as exc_info:
        service.admit(
            mission_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            admitted_by="test",
            request=MagicMock(),
        )
    assert exc_info.value.status_code == 410


@pytest.mark.parametrize(
    "route",
    [
        mission_module.worker_claim_admission,
        mission_module.worker_start_admission,
        mission_module.worker_run_admission,
    ],
)
def test_http_worker_mutation_routes_return_gone(route: object) -> None:
    with (
        patch.object(mission_module, "require_route_permission"),
        pytest.raises(HTTPException, match="daemon worker") as exc_info,
    ):
        route(  # type: ignore[operator]
            mission_id=uuid.uuid4(),
            request=MagicMock(),
            tenant_id=uuid.uuid4(),
            db=MagicMock(),
        )
    assert exc_info.value.status_code == 410
