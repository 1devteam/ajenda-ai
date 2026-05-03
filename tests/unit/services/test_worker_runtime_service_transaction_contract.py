"""Transaction-boundary drift guards for WorkerRuntimeService.

WorkerLoop and TaskDispatcher delegate runtime state transitions to
WorkerRuntimeService. These tests make that contract explicit: runtime service
methods that mutate queue/database state own their session commit boundary.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Callable
from typing import Any

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
    return isinstance(owner, ast.Name) and owner.id == "self" and target.attr == "_session" and callee.attr == session_method


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


def test_worker_runtime_queue_rejection_paths_roll_back_session_before_raise() -> None:
    queue_mutation_methods: tuple[RuntimeMethod, ...] = (
        WorkerRuntimeService.complete,
        WorkerRuntimeService.fail,
        WorkerRuntimeService.release,
    )

    for method in queue_mutation_methods:
        rejection_branch = _queue_rejection_branch(method)
        rollback_lines = [node.lineno for node in ast.walk(rejection_branch) if _is_session_method_call(node, "rollback")]
        raise_lines = [node.lineno for node in ast.walk(rejection_branch) if isinstance(node, ast.Raise)]

        assert rollback_lines, f"{method.__name__} must roll back inside the queue rejection branch"
        assert raise_lines, f"{method.__name__} must raise inside the queue rejection branch"
        assert min(rollback_lines) < min(raise_lines), f"{method.__name__} must roll back before raising"


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
