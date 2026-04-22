from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from backend.services.execution_coordinator import ExecutionCoordinator


def test_require_task_raises_when_task_missing() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()
    coordinator._tasks.get.return_value = None

    with pytest.raises(ValueError, match="task not found for tenant"):
        coordinator._require_task(task_id=uuid.uuid4(), tenant_id=str(uuid.uuid4()))


def test_require_task_raises_when_task_belongs_to_other_tenant() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()

    task = MagicMock()
    task.tenant_id = str(uuid.uuid4())
    coordinator._tasks.get.return_value = task

    with pytest.raises(ValueError, match="task not found for tenant"):
        coordinator._require_task(task_id=uuid.uuid4(), tenant_id=str(uuid.uuid4()))


def test_require_task_returns_task_for_matching_tenant() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()

    tenant_id = str(uuid.uuid4())
    task = MagicMock()
    task.tenant_id = tenant_id
    coordinator._tasks.get.return_value = task

    result = coordinator._require_task(task_id=uuid.uuid4(), tenant_id=tenant_id)

    assert result is task
