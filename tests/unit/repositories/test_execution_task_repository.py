from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.domain.execution_task import ExecutionTask
from backend.repositories.execution_task_repository import ExecutionTaskRepository


def test_cancel_planned_by_ids_for_mission_only_updates_matching_planned_tasks() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    task_id = uuid.uuid4()
    task = ExecutionTask(
        id=task_id,
        tenant_id=tenant_id,
        mission_id=mission_id,
        title="Materialized task",
        description="Planned materialized task",
        status="planned",
        metadata_json={},
    )
    session = MagicMock()
    session.scalars.return_value = [task]

    result = ExecutionTaskRepository(session).cancel_planned_by_ids_for_mission(
        tenant_id=tenant_id,
        mission_id=mission_id,
        task_ids=[task_id],
    )

    assert result == [task]
    assert task.status == "cancelled"
    statement = session.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "execution_tasks.id" in compiled
    assert "execution_tasks.tenant_id" in compiled
    assert "execution_tasks.mission_id" in compiled
    assert "execution_tasks.status" in compiled
    assert tenant_id in compiled
    session.add.assert_called_once_with(task)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(task)


def test_cancel_planned_by_ids_for_mission_skips_empty_id_list() -> None:
    session = MagicMock()

    result = ExecutionTaskRepository(session).cancel_planned_by_ids_for_mission(
        tenant_id="tenant-a",
        mission_id=uuid.uuid4(),
        task_ids=[],
    )

    assert result == []
    session.scalars.assert_not_called()
    session.flush.assert_not_called()


def test_list_for_mission_for_tenant_enforces_both_scope_keys() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    task = MagicMock(spec=ExecutionTask)
    session = MagicMock()
    session.scalars.return_value = [task]

    result = ExecutionTaskRepository(session).list_for_mission_for_tenant(
        mission_id=mission_id,
        tenant_id=tenant_id,
    )

    assert result == [task]
    statement = session.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "execution_tasks.mission_id" in compiled
    assert "execution_tasks.tenant_id" in compiled
    assert str(mission_id) in compiled
    assert tenant_id in compiled
    assert "ORDER BY execution_tasks.created_at ASC, execution_tasks.id ASC" in compiled
