"""Transaction-boundary drift guards for WorkerRuntimeService.

WorkerLoop and TaskDispatcher delegate runtime state transitions to
WorkerRuntimeService. These tests make that contract explicit: runtime service
methods that mutate queue/database state own their session commit boundary.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import uuid
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.queue.base import QueueOperationResult
from backend.services.worker_runtime_service import WorkerRuntimeService

RuntimeMethod = Callable[..., Any]


def _method_ast(method: RuntimeMethod) -> ast.FunctionDef:
    source = textwrap.dedent(inspect.getsource(method))
    module = ast.parse(source)
    function = module.body[0]
    assert isinstance(function, ast.FunctionDef)
    return function


def _calls_session_method(method: RuntimeMethod, session_method: str) -> bool:
    function = _method_ast(method)
    for node in ast.walk(function):
        if _is_session_method_call(node, session_method):
            return True
    return False


def _is_session_method_call(node: ast.AST, session_method: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    callee = node.func
    if not isinstance(callee, ast.Attribute):
        return False
    target = callee.value
    if not isinstance(target, ast.Attribute):
        return False
    owner = target.value
    return (
        isinstance(owner, ast.Name)
        and owner.id == "self"
        and target.attr == "_session"
        and callee.attr == session_method
    )


def _session_method_line_numbers(method: RuntimeMethod, session_method: str) -> list[int]:
    function = _method_ast(method)
    return [node.lineno for node in ast.walk(function) if _is_session_method_call(node, session_method)]


def _queue_rejection_branch(method: RuntimeMethod) -> ast.If:
    function = _method_ast(method)
    for node in ast.walk(function):
        if isinstance(node, ast.If) and ast.unparse(node.test) == "not result.ok":
            return node
    raise AssertionError(f"{method.__name__} must branch on rejected queue result")


def _lineage_append_line_number(function: ast.FunctionDef) -> int:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "append" and "LineageRecordRepository" in ast.unparse(node.func.value):
            return node.lineno
    raise AssertionError("complete must append task output lineage")


def _audit_append_line_number(function: ast.FunctionDef) -> int:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "append" and ast.unparse(node.func.value) == "self._audit":
            return node.lineno
    raise AssertionError("complete must append worker audit evidence")


def test_worker_runtime_mutating_task_methods_own_commit_boundary() -> None:
    mutating_task_methods: tuple[RuntimeMethod, ...] = (
        WorkerRuntimeService.claim_next_task,
        WorkerRuntimeService.start_execution,
        WorkerRuntimeService.complete,
        WorkerRuntimeService.fail,
    )

    for method in mutating_task_methods:
        assert _calls_session_method(method, "commit"), f"{method.__name__} must commit its session boundary"


def test_worker_runtime_mutating_lease_methods_own_commit_boundary() -> None:
    mutating_lease_methods: tuple[RuntimeMethod, ...] = (
        WorkerRuntimeService.heartbeat,
        WorkerRuntimeService.release,
    )

    for method in mutating_lease_methods:
        assert _calls_session_method(method, "commit"), f"{method.__name__} must commit its session boundary"


def test_worker_runtime_release_queue_rejection_rolls_back_before_raise() -> None:
    rejection_branch = _queue_rejection_branch(WorkerRuntimeService.release)
    rollback_lines = [node.lineno for node in ast.walk(rejection_branch) if _is_session_method_call(node, "rollback")]
    raise_lines = [node.lineno for node in ast.walk(rejection_branch) if isinstance(node, ast.Raise)]

    assert rollback_lines, "release must roll back inside the queue rejection branch"
    assert raise_lines, "release must raise inside the queue rejection branch"
    assert min(rollback_lines) < min(raise_lines), "release must roll back before raising"


def test_worker_runtime_terminal_db_commit_precedes_irreversible_queue_cleanup() -> None:
    for method in (WorkerRuntimeService.complete, WorkerRuntimeService.fail):
        function = _method_ast(method)
        commit_lines = _session_method_line_numbers(method, "commit")
        queue_cleanup_lines = [
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"complete_task", "fail_task"}
        ]

        assert commit_lines, f"{method.__name__} must durably commit DB terminal truth"
        assert queue_cleanup_lines, f"{method.__name__} must still clean up queue processing payloads"
        assert max(commit_lines) < min(queue_cleanup_lines), (
            f"{method.__name__} must commit DB terminal truth before irreversible queue cleanup"
        )


def test_worker_runtime_complete_persists_lineage_and_audit_before_commit() -> None:
    complete_ast = _method_ast(WorkerRuntimeService.complete)
    lineage_append_line = _lineage_append_line_number(complete_ast)
    audit_append_line = _audit_append_line_number(complete_ast)
    commit_lines = _session_method_line_numbers(WorkerRuntimeService.complete, "commit")

    assert commit_lines
    assert lineage_append_line < max(commit_lines)
    assert audit_append_line < max(commit_lines)


def test_worker_runtime_claim_records_worker_lease_id_before_commit() -> None:
    claim_ast = _method_ast(WorkerRuntimeService.claim_next_task)
    lease_metadata_assignment_found = False

    for node in ast.walk(claim_ast):
        if not isinstance(node, ast.Assign):
            continue
        targets = [ast.unparse(target) for target in node.targets]
        if "task.metadata_json" in targets and "worker_lease_id" in ast.unparse(node.value):
            lease_metadata_assignment_found = True

    assert lease_metadata_assignment_found


def test_worker_runtime_public_mutators_keep_return_contracts() -> None:
    assert inspect.signature(WorkerRuntimeService.claim_next_task).return_annotation == "ExecutionTask | None"
    assert inspect.signature(WorkerRuntimeService.start_execution).return_annotation == "ExecutionTask"
    assert inspect.signature(WorkerRuntimeService.complete).return_annotation == "ExecutionTask"
    assert inspect.signature(WorkerRuntimeService.fail).return_annotation == "ExecutionTask"
    assert inspect.signature(WorkerRuntimeService.heartbeat).return_annotation == "WorkerLease"
    assert inspect.signature(WorkerRuntimeService.release).return_annotation == "WorkerLease"


def test_worker_runtime_release_requeues_claimed_task_state_with_queue_payload() -> None:
    session = MagicMock()
    queue = MagicMock()
    queue.release_lease.return_value = QueueOperationResult(ok=True)
    service = WorkerRuntimeService(session, queue)
    tenant_id = "tenant-release-contract"
    worker_id = "worker-release-contract"
    lease = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        holder_identity=worker_id,
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=None,
    )
    task = SimpleNamespace(
        id=lease.task_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.CLAIMED.value,
        metadata_json={"worker_lease_id": str(lease.id)},
    )
    service._leases = MagicMock()
    service._leases.get.return_value = lease
    service._tasks = MagicMock()
    service._tasks.get.return_value = task

    released = service.release(tenant_id=tenant_id, lease_id=lease.id, worker_id=worker_id)

    assert released is lease
    assert lease.status == WorkerLeaseState.RELEASED.value
    assert task.status == ExecutionTaskState.QUEUED.value
    queue.release_lease.assert_called_once_with(
        tenant_id=tenant_id,
        task_id=lease.task_id,
        worker_id=worker_id,
    )
    session.flush.assert_called_once()
    session.commit.assert_called_once()
    session.rollback.assert_not_called()


def test_worker_runtime_release_fails_closed_when_task_is_not_claimed() -> None:
    session = MagicMock()
    queue = MagicMock()
    queue.release_lease.return_value = QueueOperationResult(ok=True)
    service = WorkerRuntimeService(session, queue)
    tenant_id = "tenant-release-running"
    worker_id = "worker-release-running"
    lease = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        holder_identity=worker_id,
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=None,
    )
    task = SimpleNamespace(
        id=lease.task_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.RUNNING.value,
        metadata_json={"worker_lease_id": str(lease.id)},
    )
    service._leases = MagicMock()
    service._leases.get.return_value = lease
    service._tasks = MagicMock()
    service._tasks.get.return_value = task

    try:
        service.release(tenant_id=tenant_id, lease_id=lease.id, worker_id=worker_id)
    except ValueError as exc:
        assert str(exc) == "task is not claimed"
    else:
        raise AssertionError("running task release must fail closed")

    assert lease.status == WorkerLeaseState.ACTIVE.value
    assert task.status == ExecutionTaskState.RUNNING.value
    queue.release_lease.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize("stale_status", [WorkerLeaseState.EXPIRED.value, WorkerLeaseState.RELEASED.value])
def test_worker_runtime_release_fails_closed_for_non_releasable_stale_lease(stale_status: str) -> None:
    session = MagicMock()
    queue = MagicMock()
    queue.release_lease.return_value = QueueOperationResult(ok=True)
    service = WorkerRuntimeService(session, queue)
    tenant_id = "tenant-release-stale"
    old_worker_id = "worker-release-stale-old"
    old_lease = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        holder_identity=old_worker_id,
        status=stale_status,
        heartbeat_at=None,
    )
    newer_lease_id = uuid.uuid4()
    task = SimpleNamespace(
        id=old_lease.task_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.CLAIMED.value,
        metadata_json={"worker_lease_id": str(newer_lease_id)},
    )
    service._leases = MagicMock()
    service._leases.get.return_value = old_lease
    service._tasks = MagicMock()
    service._tasks.get.return_value = task

    try:
        service.release(tenant_id=tenant_id, lease_id=old_lease.id, worker_id=old_worker_id)
    except ValueError as exc:
        assert str(exc) == "lease is not release-eligible"
    else:
        raise AssertionError("stale expired lease release must fail closed")

    assert old_lease.status == stale_status
    assert task.status == ExecutionTaskState.CLAIMED.value
    assert task.metadata_json["worker_lease_id"] == str(newer_lease_id)
    queue.release_lease.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()


def test_worker_runtime_release_fails_closed_when_claim_metadata_points_to_newer_lease() -> None:
    session = MagicMock()
    queue = MagicMock()
    queue.release_lease.return_value = QueueOperationResult(ok=True)
    service = WorkerRuntimeService(session, queue)
    tenant_id = "tenant-release-superseded"
    old_worker_id = "worker-release-superseded-old"
    old_lease = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        task_id=uuid.uuid4(),
        holder_identity=old_worker_id,
        status=WorkerLeaseState.ACTIVE.value,
        heartbeat_at=None,
    )
    newer_lease_id = uuid.uuid4()
    task = SimpleNamespace(
        id=old_lease.task_id,
        tenant_id=tenant_id,
        status=ExecutionTaskState.CLAIMED.value,
        metadata_json={"worker_lease_id": str(newer_lease_id)},
    )
    service._leases = MagicMock()
    service._leases.get.return_value = old_lease
    service._tasks = MagicMock()
    service._tasks.get.return_value = task

    try:
        service.release(tenant_id=tenant_id, lease_id=old_lease.id, worker_id=old_worker_id)
    except ValueError as exc:
        assert str(exc) == "lease is not current task claim"
    else:
        raise AssertionError("superseded lease release must fail closed")

    assert old_lease.status == WorkerLeaseState.ACTIVE.value
    assert task.status == ExecutionTaskState.CLAIMED.value
    assert task.metadata_json["worker_lease_id"] == str(newer_lease_id)
    queue.release_lease.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
