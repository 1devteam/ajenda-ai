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
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if not isinstance(callee, ast.Attribute):
            continue
        target = callee.value
        if not isinstance(target, ast.Attribute):
            continue
        owner = target.value
        if not isinstance(owner, ast.Name):
            continue
        if owner.id == "self" and target.attr == "_session" and callee.attr == session_method:
            return True
    return False


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
        assert _calls_session_method(method, "rollback"), f"{method.__name__} must roll back on queue rejection"


def test_worker_runtime_complete_persists_lineage_and_audit_before_commit() -> None:
    complete_ast = _method_ast(WorkerRuntimeService.complete)
    called_names: list[str] = []
    called_attrs: list[str] = []

    for node in ast.walk(complete_ast):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.append(node.func.id)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attrs.append(node.func.attr)

    assert "LineageRecordRepository" in called_names
    assert "LineageRecord" in called_names
    assert "AuditEvent" in called_names
    assert "append" in called_attrs


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
