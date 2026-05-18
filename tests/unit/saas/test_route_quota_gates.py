from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.routes import api_keys as api_key_routes
from backend.api.routes import mission as mission_routes
from backend.api.routes import task as task_routes
from backend.api.routes import workforce as workforce_routes
from backend.domain.enums import ExecutionTaskState
from backend.services.quota_enforcement import QuotaExceededError


def _request() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(subject_id="user-1")))


def _quota_error() -> QuotaExceededError:
    return QuotaExceededError(
        field="tasks_per_month",
        limit=10,
        current=10,
        plan="free",
    )


def test_task_queue_checks_quota_before_queueing() -> None:
    tenant_id = str(uuid.uuid4())
    task_id = uuid.uuid4()
    result = SimpleNamespace(ok=True, task_id=task_id, state="queued")

    with (
        patch("backend.api.routes.task.QuotaEnforcementService") as quota_cls,
        patch("backend.api.routes.task.ExecutionCoordinator") as coordinator_cls,
    ):
        quota = MagicMock()
        quota_cls.return_value = quota
        coordinator = MagicMock()
        coordinator.queue_task.return_value = result
        coordinator_cls.return_value = coordinator

        response = task_routes.queue_task(
            task_id=task_id,
            tenant_id=tenant_id,
            db=MagicMock(),
            queue=MagicMock(),
        )

    quota.check_and_record_task_creation.assert_called_once_with(uuid.UUID(tenant_id))
    assert response == {"task_id": str(task_id), "state": "queued"}


def test_task_queue_maps_quota_error_to_429() -> None:
    with patch("backend.api.routes.task.QuotaEnforcementService") as quota_cls:
        quota = MagicMock()
        quota.check_and_record_task_creation.side_effect = _quota_error()
        quota_cls.return_value = quota

        with pytest.raises(HTTPException) as exc_info:
            task_routes.queue_task(
                task_id=uuid.uuid4(),
                tenant_id=str(uuid.uuid4()),
                db=MagicMock(),
                queue=MagicMock(),
            )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "QUOTA_EXCEEDED"


def test_mission_queue_charges_planned_tasks_for_same_tenant_only() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    queued_id = uuid.uuid4()
    tasks = [
        SimpleNamespace(tenant_id=tenant_id, status=ExecutionTaskState.PLANNED.value),
        SimpleNamespace(tenant_id=tenant_id, status=ExecutionTaskState.COMPLETED.value),
        SimpleNamespace(tenant_id=str(uuid.uuid4()), status=ExecutionTaskState.PLANNED.value),
    ]

    with (
        patch("backend.api.routes.mission.ExecutionTaskRepository") as repo_cls,
        patch("backend.api.routes.mission.QuotaEnforcementService") as quota_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
    ):
        repo = MagicMock()
        repo.list_for_mission.return_value = tasks
        repo_cls.return_value = repo
        quota = MagicMock()
        quota_cls.return_value = quota
        executor = MagicMock()
        executor.queue_all_planned_tasks.return_value = [queued_id]
        executor_cls.return_value = executor

        response = mission_routes.queue_mission(
            mission_id=mission_id,
            tenant_id=tenant_id,
            db=MagicMock(),
            queue=MagicMock(),
        )

    quota.check_and_record_task_creation.assert_called_once_with(
        uuid.UUID(tenant_id),
        count=1,
    )
    assert response == {"queued_task_ids": [str(queued_id)]}


def test_mission_queue_returns_empty_without_planned_tasks() -> None:
    with (
        patch("backend.api.routes.mission.ExecutionTaskRepository") as repo_cls,
        patch("backend.api.routes.mission.QuotaEnforcementService") as quota_cls,
        patch("backend.api.routes.mission.MissionExecutor") as executor_cls,
    ):
        repo = MagicMock()
        repo.list_for_mission.return_value = []
        repo_cls.return_value = repo

        response = mission_routes.queue_mission(
            mission_id=uuid.uuid4(),
            tenant_id=str(uuid.uuid4()),
            db=MagicMock(),
            queue=MagicMock(),
        )

    quota_cls.assert_not_called()
    executor_cls.assert_not_called()
    assert response == {"queued_task_ids": []}


def test_workforce_provision_checks_agent_quota() -> None:
    tenant_id = str(uuid.uuid4())
    fleet_id = uuid.uuid4()
    body = workforce_routes.ProvisionFleetRequest(
        mission_id=str(uuid.uuid4()),
        fleet_name="fleet-a",
        agents=[
            workforce_routes.AgentSpec(display_name="A", role_name="analyst"),
            workforce_routes.AgentSpec(display_name="B", role_name="builder"),
        ],
    )

    with (
        patch("backend.api.routes.workforce.QuotaEnforcementService") as quota_cls,
        patch("backend.api.routes.workforce.WorkforceProvisioner") as provisioner_cls,
    ):
        quota = MagicMock()
        quota_cls.return_value = quota
        provisioner = MagicMock()
        provisioner.provision_fleet.return_value = SimpleNamespace(id=fleet_id, status="planned")
        provisioner_cls.return_value = provisioner

        response = workforce_routes.provision_workforce(
            body=body,
            tenant_id=tenant_id,
            db=MagicMock(),
        )

    quota.check_and_record_agent_provisioning.assert_called_once_with(
        uuid.UUID(tenant_id),
        agents_requested=2,
    )
    assert response == {"fleet_id": str(fleet_id), "state": "planned"}


def test_api_key_creation_checks_active_key_quota() -> None:
    tenant_id = str(uuid.uuid4())
    body = api_key_routes.CreateApiKeyRequest(scopes=["execution:queue"])
    record = SimpleNamespace(
        key_id="key-1",
        tenant_id=tenant_id,
        scopes_json=["execution:queue"],
    )

    with (
        patch("backend.api.routes.api_keys.AuthorizationService") as authz_cls,
        patch("backend.api.routes.api_keys.ApiKeyService") as service_cls,
        patch("backend.api.routes.api_keys.QuotaEnforcementService") as quota_cls,
    ):
        authz_cls.return_value.require.return_value = None
        service = MagicMock()
        service.count_active_keys.return_value = 1
        service.create_key.return_value = ("secret", record)
        service_cls.return_value = service
        quota = MagicMock()
        quota_cls.return_value = quota

        response = api_key_routes.create_api_key(
            body=body,
            request=_request(),
            tenant_id=tenant_id,
            db=MagicMock(),
        )

    quota.check_api_key_limit.assert_called_once_with(
        uuid.UUID(tenant_id),
        current_key_count=1,
    )
    assert response["plaintext_key"] == "key-1.secret"
