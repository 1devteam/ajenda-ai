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
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.domain.enums import ExecutionTaskState, WorkerLeaseState
from backend.queue.base import QueueMessage, QueueOperationResult
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
        WorkerRuntimeService.block_completion_failure,
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
    assert inspect.signature(WorkerRuntimeService.block_completion_failure).return_annotation == "ExecutionTask"
    assert inspect.signature(WorkerRuntimeService.fail).return_annotation == "ExecutionTask"
    assert inspect.signature(WorkerRuntimeService.heartbeat).return_annotation == "WorkerLease"
    assert inspect.signature(WorkerRuntimeService.release).return_annotation == "WorkerLease"


def _terminal_runtime_subject(
    *, status: str
) -> tuple[WorkerRuntimeService, MagicMock, MagicMock, SimpleNamespace, SimpleNamespace, str, str]:
    session = MagicMock()
    queue = MagicMock()
    service = WorkerRuntimeService(session, queue)
    tenant_id = "tenant-terminal-ack"
    worker_id = "worker-terminal-ack"
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
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        status=status,
        metadata_json={"worker_lease_id": str(lease.id)},
    )
    service._leases = MagicMock()
    service._leases.get.return_value = lease
    service._tasks = MagicMock()
    service._tasks.get.return_value = task
    service._audit = MagicMock()
    return service, session, queue, lease, task, tenant_id, worker_id


def test_complete_mirrors_handler_result_and_output_to_task_metadata() -> None:
    service, _session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=True)
    task_output = {
        "handler": "echo",
        "status": "completed",
        "output": {"count": 2},
    }

    service.complete(
        tenant_id=tenant_id,
        lease_id=lease.id,
        worker_id=worker_id,
        task_output=task_output,
        output_reason="echo handler completed",
    )

    assert task.metadata_json["handler_result"] == task_output
    assert task.metadata_json["output"] == {"count": 2}


def test_complete_rejects_declared_output_contract_without_handler_output() -> None:
    service, _session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    task.metadata_json["expected_output_contract"] = {"artifact": "research_brief"}

    with pytest.raises(ValueError, match="must provide output for declared artifact"):
        service.complete(
            tenant_id=tenant_id,
            lease_id=lease.id,
            worker_id=worker_id,
            task_output={"handler": "tool.invoke", "status": "completed"},
        )

    assert task.status == ExecutionTaskState.RUNNING.value
    queue.complete_task.assert_not_called()


def test_complete_rejects_output_that_does_not_emit_declared_artifact() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    task.metadata_json["expected_output_contract"] = {"artifact": "research_brief"}

    with pytest.raises(ValueError, match="must emit declared artifact 'research_brief'"):
        service.complete(
            tenant_id=tenant_id,
            lease_id=lease.id,
            worker_id=worker_id,
            task_output={
                "handler": "tool.invoke",
                "status": "completed",
                "output": {"different_artifact": {"summary": "wrong key"}},
            },
        )

    assert task.status == ExecutionTaskState.RUNNING.value
    assert lease.status == WorkerLeaseState.ACTIVE.value
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    queue.complete_task.assert_not_called()


def test_complete_rejects_empty_declared_prospect_candidates() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    task.metadata_json["expected_output_contract"] = {"artifact": "prospect_candidates"}

    with pytest.raises(
        ValueError,
        match="typed per-item artifact payload must contain at least one item",
    ):
        service.complete(
            tenant_id=tenant_id,
            lease_id=lease.id,
            worker_id=worker_id,
            task_output={
                "handler": "tool.invoke",
                "status": "completed",
                "output": {"prospect_candidates": []},
            },
        )

    assert task.status == ExecutionTaskState.RUNNING.value
    queue.complete_task.assert_not_called()


def test_complete_allows_explicit_intermediate_public_discovery_payload() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=True)
    task.metadata_json["expected_output_contract"] = {
        "artifact": "prospect_candidates",
        "materialization_role": "intermediate",
        "allow_empty": True,
    }
    task.metadata_json["tool_invocation"] = {
        "action": "web.research",
        "input": {"include_public_search": True},
    }

    service.complete(
        tenant_id=tenant_id,
        lease_id=lease.id,
        worker_id=worker_id,
        task_output={
            "handler": "artifact-test",
            "status": "completed",
            "output": {
                "prospect_candidates": [
                    {
                        "company": "Directory listing",
                        "website": "https://directory.example/hvac",
                        "identity_status": "unverified",
                        "real": False,
                    }
                ]
            },
        },
    )

    assert task.status == ExecutionTaskState.COMPLETED.value


def test_complete_rejects_typed_declared_artifact_with_invalid_schema() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    task.metadata_json["expected_output_contract"] = {"artifact": "prospect_candidates"}

    with pytest.raises(
        ValueError,
        match="declared artifact 'prospect_candidates' failed schema validation: "
        "item 0 missing required field: sources",
    ):
        service.complete(
            tenant_id=tenant_id,
            lease_id=lease.id,
            worker_id=worker_id,
            task_output={
                "handler": "tool.invoke",
                "status": "completed",
                "output": {
                    "prospect_candidates": [
                        {
                            "website": "https://acme.example",
                            "product_description": "",
                            "research_summary": "Acme was identified in a public result.",
                        }
                    ]
                },
            },
        )

    assert task.status == ExecutionTaskState.RUNNING.value
    assert lease.status == WorkerLeaseState.ACTIVE.value
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    queue.complete_task.assert_not_called()


def test_complete_accepts_typed_declared_artifact_with_valid_schema() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=True)
    task.metadata_json["expected_output_contract"] = {"artifact": "prospect_candidates"}
    task_output = {
        "handler": "artifact-test",
        "status": "completed",
        "output": {
            "prospect_candidates": [
                {
                    "website": "https://acme.example",
                    "product_description": "",
                    "research_summary": "Acme was identified in a public result.",
                    "sources": ["https://acme.example"],
                }
            ]
        },
    }

    completed = service.complete(
        tenant_id=tenant_id,
        lease_id=lease.id,
        worker_id=worker_id,
        task_output=task_output,
        output_reason="tool action completed",
    )

    assert completed is task
    assert task.status == ExecutionTaskState.COMPLETED.value
    assert lease.status == WorkerLeaseState.RELEASED.value
    assert task.metadata_json["handler_result"] == task_output
    assert task.metadata_json["output"] == task_output["output"]
    session.commit.assert_called_once()
    queue.complete_task.assert_called_once_with(
        tenant_id=tenant_id,
        task_id=task.id,
        worker_id=worker_id,
    )


def test_complete_accepts_exact_untyped_declared_artifact_payload() -> None:
    service, _session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=True)
    task.metadata_json["expected_output_contract"] = {"artifact": "research_brief"}

    completed = service.complete(
        tenant_id=tenant_id,
        lease_id=lease.id,
        worker_id=worker_id,
        task_output={
            "handler": "artifact-test",
            "status": "completed",
            "output": {"research_brief": {"summary": "Verified research."}},
        },
    )

    assert completed is task
    assert task.status == ExecutionTaskState.COMPLETED.value
    queue.complete_task.assert_called_once()


def test_complete_commits_db_when_queue_complete_ack_fails() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=False, reason="redis timeout")

    completed = service.complete(tenant_id=tenant_id, lease_id=lease.id, worker_id=worker_id)

    assert completed is task
    assert task.status == ExecutionTaskState.COMPLETED.value
    assert lease.status == WorkerLeaseState.RELEASED.value
    queue.complete_task.assert_called_once_with(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
    queue.fail_task.assert_not_called()
    assert session.commit.call_count == 2
    session.rollback.assert_not_called()
    assert service._audit.append.call_args_list[-1].args[0].action == "terminal_queue_complete_cleanup_failed"


def test_fail_commits_db_when_queue_fail_ack_fails() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.fail_task.return_value = QueueOperationResult(ok=False, reason="redis timeout")

    failed = service.fail(tenant_id=tenant_id, lease_id=lease.id, worker_id=worker_id, reason="handler failed")

    assert failed is task
    assert task.status == ExecutionTaskState.FAILED.value
    assert lease.status == WorkerLeaseState.RELEASED.value
    queue.fail_task.assert_called_once_with(
        tenant_id=tenant_id,
        task_id=task.id,
        worker_id=worker_id,
        reason="handler failed",
    )
    queue.complete_task.assert_not_called()
    assert session.commit.call_count == 2
    session.rollback.assert_not_called()
    assert service._audit.append.call_args_list[-1].args[0].action == "terminal_queue_fail_cleanup_failed"


def test_fail_persists_rejected_failure_evidence_without_artifact() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.fail_task.return_value = QueueOperationResult(ok=True)

    service.fail(tenant_id=tenant_id, lease_id=lease.id, worker_id=worker_id, reason="cross-origin blocked")

    evidence = [call.args[0] for call in session.add.call_args_list if hasattr(call.args[0], "evidence_type")]
    assert len(evidence) == 1
    assert evidence[0].evidence_type == "execution_failure"
    assert evidence[0].collection_status == "rejected"
    assert evidence[0].execution_task_id == task.id
    assert evidence[0].artifact_references == []
    assert evidence[0].structured_payload["artifact_produced"] is False


def test_complete_queue_ack_failure_does_not_rerun_or_fail_completed_work() -> None:
    service, _session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=False, reason="ack failed after DB commit")

    service.complete(tenant_id=tenant_id, lease_id=lease.id, worker_id=worker_id)

    assert task.status == ExecutionTaskState.COMPLETED.value
    queue.fail_task.assert_not_called()


def test_terminal_queue_ack_failure_keeps_lease_released() -> None:
    service, _session, queue, lease, _task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=False, reason="ack failed after DB commit")

    service.complete(tenant_id=tenant_id, lease_id=lease.id, worker_id=worker_id)

    assert lease.status == WorkerLeaseState.RELEASED.value


def test_claim_next_task_reconciles_terminal_queue_artifact_without_claiming() -> None:
    session = MagicMock()
    queue = MagicMock()
    service = WorkerRuntimeService(session, queue)
    tenant_id = "tenant-terminal-claim"
    worker_id = "worker-terminal-claim"
    task_id = uuid.uuid4()
    task = SimpleNamespace(
        id=task_id,
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        status=ExecutionTaskState.COMPLETED.value,
        metadata_json={},
    )
    queue.claim_task.return_value = QueueMessage(
        tenant_id=tenant_id,
        task_id=task_id,
        mission_id=task.mission_id,
        fleet_id=None,
        branch_id=None,
        payload={},
        enqueued_at=datetime.now(UTC),
    )
    queue.complete_task.return_value = QueueOperationResult(ok=True)
    service._tasks = MagicMock()
    service._tasks.get.return_value = task
    service._leases = MagicMock()
    service._audit = MagicMock()

    claimed = service.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)

    assert claimed is None
    assert task.status == ExecutionTaskState.COMPLETED.value
    service._leases.add.assert_not_called()
    queue.complete_task.assert_called_once_with(tenant_id=tenant_id, task_id=task_id, worker_id=worker_id)
    queue.release_lease.assert_not_called()
    session.begin_nested.assert_not_called()
    session.flush.assert_called_once()
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    audit_event = service._audit.append.call_args.args[0]
    assert audit_event.action == "terminal_task_queue_claim_reconciled"
    assert audit_event.payload_json["requeue_allowed"] is False


def test_claim_next_task_reconciles_blocked_terminal_queue_artifact_without_claiming() -> None:
    session = MagicMock()
    queue = MagicMock()
    service = WorkerRuntimeService(session, queue)
    tenant_id = "tenant-blocked-claim"
    worker_id = "worker-blocked-claim"
    task_id = uuid.uuid4()
    task = SimpleNamespace(
        id=task_id,
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        status=ExecutionTaskState.BLOCKED.value,
        metadata_json={},
    )
    queue.claim_task.return_value = QueueMessage(
        tenant_id=tenant_id,
        task_id=task_id,
        mission_id=task.mission_id,
        fleet_id=None,
        branch_id=None,
        payload={},
        enqueued_at=datetime.now(UTC),
    )
    queue.complete_task.return_value = QueueOperationResult(ok=True)
    service._tasks = MagicMock()
    service._tasks.get.return_value = task
    service._leases = MagicMock()
    service._audit = MagicMock()

    claimed = service.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)

    assert claimed is None
    assert task.status == ExecutionTaskState.BLOCKED.value
    service._leases.add.assert_not_called()
    queue.complete_task.assert_called_once_with(tenant_id=tenant_id, task_id=task_id, worker_id=worker_id)
    audit_event = service._audit.append.call_args.args[0]
    assert audit_event.action == "terminal_task_queue_claim_reconciled"
    assert audit_event.payload_json["requeue_allowed"] is False


def test_claim_next_task_records_terminal_queue_artifact_cleanup_failure() -> None:
    session = MagicMock()
    queue = MagicMock()
    service = WorkerRuntimeService(session, queue)
    tenant_id = "tenant-terminal-claim-failure"
    worker_id = "worker-terminal-claim-failure"
    task_id = uuid.uuid4()
    task = SimpleNamespace(
        id=task_id,
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        status=ExecutionTaskState.FAILED.value,
        metadata_json={},
    )
    queue.claim_task.return_value = QueueMessage(
        tenant_id=tenant_id,
        task_id=task_id,
        mission_id=task.mission_id,
        fleet_id=None,
        branch_id=None,
        payload={},
        enqueued_at=datetime.now(UTC),
    )
    queue.complete_task.return_value = QueueOperationResult(ok=False, reason="cleanup rejected")
    service._tasks = MagicMock()
    service._tasks.get.return_value = task
    service._leases = MagicMock()
    service._audit = MagicMock()

    claimed = service.claim_next_task(tenant_id=tenant_id, worker_id=worker_id)

    assert claimed is None
    assert task.status == ExecutionTaskState.FAILED.value
    service._leases.add.assert_not_called()
    queue.complete_task.assert_called_once_with(tenant_id=tenant_id, task_id=task_id, worker_id=worker_id)
    queue.fail_task.assert_not_called()
    session.begin_nested.assert_not_called()
    session.flush.assert_called_once()
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    audit_event = service._audit.append.call_args.args[0]
    assert audit_event.action == "terminal_task_queue_claim_cleanup_failed"
    assert audit_event.payload_json["cleanup_succeeded"] is False
    assert audit_event.payload_json["requeue_allowed"] is False


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


def test_block_completion_failure_blocks_task_releases_lease_and_cleans_queue_claim() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=True)

    blocked = service.block_completion_failure(
        tenant_id=tenant_id,
        lease_id=lease.id,
        worker_id=worker_id,
        task_type="tool.invoke",
        side_effect_class="external_write",
        reason="completion evidence write failed",
    )

    assert blocked is task
    assert task.status == ExecutionTaskState.BLOCKED.value
    assert lease.status == WorkerLeaseState.RELEASED.value
    queue.complete_task.assert_called_once_with(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
    queue.fail_task.assert_not_called()
    assert session.commit.call_count == 1
    session.rollback.assert_not_called()
    audit_event = service._audit.append.call_args.args[0]
    assert audit_event.action == "task_completion_failed_after_side_effect"
    assert audit_event.payload_json == {
        "task_id": str(task.id),
        "lease_id": str(lease.id),
        "task_type": "tool.invoke",
        "side_effect_class": "external_write",
        "reason": "completion evidence write failed",
        "handler_completed": True,
        "requeue_allowed": False,
    }


def test_block_completion_failure_records_queue_cleanup_failure_without_retrying() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.RUNNING.value
    )
    queue.complete_task.return_value = QueueOperationResult(ok=False, reason="redis timeout")

    service.block_completion_failure(
        tenant_id=tenant_id,
        lease_id=lease.id,
        worker_id=worker_id,
        task_type="tool.invoke",
        side_effect_class="external_send",
        reason="completion evidence write failed",
    )

    assert task.status == ExecutionTaskState.BLOCKED.value
    assert lease.status == WorkerLeaseState.RELEASED.value
    queue.complete_task.assert_called_once_with(tenant_id=tenant_id, task_id=task.id, worker_id=worker_id)
    queue.fail_task.assert_not_called()
    assert session.commit.call_count == 2
    cleanup_audit_event = service._audit.append.call_args_list[-1].args[0]
    assert cleanup_audit_event.action == "completion_failure_queue_complete_cleanup_failed"
    assert cleanup_audit_event.payload_json["queue_operation"] == "complete_task"
    assert cleanup_audit_event.payload_json["requeue_allowed"] is False


def test_block_completion_failure_fails_closed_for_non_running_task() -> None:
    service, session, queue, lease, task, tenant_id, worker_id = _terminal_runtime_subject(
        status=ExecutionTaskState.CLAIMED.value
    )

    with pytest.raises(ValueError, match="task is not running"):
        service.block_completion_failure(
            tenant_id=tenant_id,
            lease_id=lease.id,
            worker_id=worker_id,
            task_type="tool.invoke",
            side_effect_class="external_write",
            reason="completion evidence write failed",
        )

    assert task.status == ExecutionTaskState.CLAIMED.value
    assert lease.status == WorkerLeaseState.ACTIVE.value
    queue.complete_task.assert_not_called()
    queue.fail_task.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
