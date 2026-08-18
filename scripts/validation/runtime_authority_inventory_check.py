#!/usr/bin/env python3
"""Fail closed when production runtime-authority call sites drift.

This sentinel inventories concrete authority sinks in ``backend/`` rather than
inferring runtime topology from documentation, class names, or tests. Every
observed sink must have an explicitly reviewed path, enclosing scope,
classification, and remediation disposition in ``REVIEWED_CALL_SITES``.

The inventory intentionally distinguishes admission, queue mutation, queue
claim, lifecycle mutation, dispatcher execution, and action invocation. It
therefore exposes multiple authority entry points even when they converge on a
shared dispatcher or tool engine.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"

Sink = Literal[
    "action_invoke",
    "admission",
    "dispatcher_execute",
    "queue_claim",
    "queue_enqueue",
    "runtime_claim",
    "runtime_start",
    "tool_handler_direct",
]

Classification = Literal[
    "canonical_boundary",
    "canonical_daemon_spine",
    "competing_http_spine",
    "exception_bypass",
]


@dataclass(frozen=True, order=True)
class CallSiteKey:
    """Stable identity for a runtime-authority call site, excluding line number."""

    path: str
    scope: str
    sink: Sink


@dataclass(frozen=True)
class ReviewedCallSite:
    """Human-reviewed authority classification and required disposition."""

    classification: Classification
    disposition: str


@dataclass(frozen=True)
class ObservedCallSite:
    """One AST-observed runtime-authority call site."""

    key: CallSiteKey
    line: int
    expression: str


# This is deliberately explicit. New or moved authority sinks fail the gate
# until a reviewer traces and classifies them. PR-07/PR-08 are expected to
# remove or reclassify the bypass/competing entries rather than preserve them.
REVIEWED_CALL_SITES: dict[CallSiteKey, ReviewedCallSite] = {
    CallSiteKey("backend/api/routes/ability_runtime.py", "launch_task", "admission"): ReviewedCallSite(
        "canonical_boundary", "retain through shared admission convergence"
    ),
    CallSiteKey("backend/api/routes/admin.py", "approve_task_review", "admission"): ReviewedCallSite(
        "exception_bypass", "PR-07: route through the shared admission service"
    ),
    CallSiteKey("backend/api/routes/task.py", "queue_task", "admission"): ReviewedCallSite(
        "canonical_boundary", "retain through shared admission convergence"
    ),
    CallSiteKey(
        "backend/services/execution_coordinator.py", "ExecutionCoordinator._enqueue_or_restore", "queue_enqueue"
    ): ReviewedCallSite("canonical_boundary", "retain as the sole normal queue mutation boundary"),
    CallSiteKey(
        "backend/services/mission_executor.py", "MissionExecutor.queue_all_planned_tasks", "admission"
    ): ReviewedCallSite("canonical_boundary", "compatibility caller; converge on shared admission service"),
    CallSiteKey(
        "backend/services/mission_runtime_queue_admission_service.py",
        "MissionRuntimeQueueAdmissionService.admit",
        "admission",
    ): ReviewedCallSite("canonical_boundary", "retain as mission queue admission owner"),
    CallSiteKey(
        "backend/services/operations_service.py",
        "OperationsService._recover_existing_queue_payload_or_enqueue_from_db",
        "queue_enqueue",
    ): ReviewedCallSite("exception_bypass", "PR-07/PR-09: re-admit through shared bounded recovery"),
    CallSiteKey(
        "backend/services/tools/runtime_authority.py", "ToolRuntimeAuthority.execute", "action_invoke"
    ): ReviewedCallSite("canonical_boundary", "retain as the only production action-registry invocation"),
    CallSiteKey(
        "backend/services/vertical_ops/template_service.py",
        "VerticalOpsTemplateService.queue_planned_tasks",
        "admission",
    ): ReviewedCallSite("canonical_boundary", "retain through shared admission convergence"),
    CallSiteKey(
        "backend/services/worker_run_admission_service.py", "WorkerRunAdmissionService.admit", "queue_claim"
    ): ReviewedCallSite("competing_http_spine", "PR-08: remove synchronous HTTP claim authority"),
    CallSiteKey(
        "backend/services/worker_run_admission_service.py",
        "WorkerRunAdmissionService.admit",
        "dispatcher_execute",
    ): ReviewedCallSite("competing_http_spine", "PR-08: remove synchronous HTTP dispatch authority"),
    CallSiteKey(
        "backend/services/worker_runtime_service.py", "WorkerRuntimeService.claim_next_task", "queue_claim"
    ): ReviewedCallSite("canonical_daemon_spine", "retain as converged queue claim authority"),
    CallSiteKey(
        "backend/workers/worker_loop.py", "WorkerLoop._claim_and_start_task", "runtime_claim"
    ): ReviewedCallSite("canonical_daemon_spine", "retain as daemon claim orchestration"),
    CallSiteKey(
        "backend/workers/worker_loop.py", "WorkerLoop._claim_and_start_task", "runtime_start"
    ): ReviewedCallSite("canonical_daemon_spine", "retain as daemon start orchestration"),
    CallSiteKey(
        "backend/workers/worker_loop.py", "WorkerLoop._run_claimed_task", "dispatcher_execute"
    ): ReviewedCallSite("canonical_daemon_spine", "retain as converged dispatcher entry point"),
}


def _attribute_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _receiver_name(node: ast.expr) -> str:
    if not isinstance(node, ast.Attribute):
        return ""
    value = node.value
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        return value.attr
    if isinstance(value, ast.Call):
        return _attribute_name(value.func) or ""
    return ""


def _sink_for_call(
    node: ast.Call,
    *,
    dispatcher_names: set[str] | None = None,
    direct_tool_handler_names: set[str] | None = None,
) -> Sink | None:
    name = _attribute_name(node.func)
    receiver = _receiver_name(node.func)
    if name in {"queue_task", "approve_review_and_queue"}:
        return "admission"
    if name == "enqueue_task":
        return "queue_enqueue"
    if name in {"claim_task", "claim_existing_task"}:
        return "queue_claim"
    if name == "claim_next_task":
        return "runtime_claim"
    if name == "start_execution":
        return "runtime_start"
    if name == "invoke":
        return "action_invoke"
    if name == "tool_invoke_handler" or name in (direct_tool_handler_names or set()):
        return "tool_handler_direct"
    if name == "execute" and receiver in ({"dispatcher", "TaskDispatcher"} | (dispatcher_names or set())):
        return "dispatcher_execute"
    return None


class _AuthorityCallVisitor(ast.NodeVisitor):
    def __init__(self, *, relative_path: str) -> None:
        self.relative_path = relative_path
        self.scope: list[str] = []
        self.observed: list[ObservedCallSite] = []
        self.dispatcher_factories: set[str] = {"TaskDispatcher"}
        self.dispatcher_names: set[str] = {"dispatcher"}
        self.direct_tool_handler_names: set[str] = {"tool_invoke_handler"}

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "backend.workers.task_dispatcher":
            for alias in node.names:
                if alias.name == "TaskDispatcher":
                    self.dispatcher_factories.add(alias.asname or alias.name)
        if node.module == "backend.workers.handlers.tool_invoke":
            for alias in node.names:
                if alias.name == "tool_invoke_handler":
                    self.direct_tool_handler_names.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            factory = _attribute_name(node.value.func)
            if factory in self.dispatcher_factories or factory == "_task_dispatcher_cls":
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.dispatcher_names.add(target.id)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        sink = _sink_for_call(
            node,
            dispatcher_names=self.dispatcher_names,
            direct_tool_handler_names=self.direct_tool_handler_names,
        )
        if sink is not None:
            self.observed.append(
                ObservedCallSite(
                    key=CallSiteKey(
                        path=self.relative_path,
                        scope=".".join(self.scope) or "<module>",
                        sink=sink,
                    ),
                    line=node.lineno,
                    expression=ast.unparse(node.func),
                )
            )
        self.generic_visit(node)


def inventory_runtime_authority(root: Path = BACKEND_ROOT) -> list[ObservedCallSite]:
    """Return concrete runtime-authority call sites under a production source root."""

    observed: list[ObservedCallSite] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else path.as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _AuthorityCallVisitor(relative_path=relative)
        visitor.visit(tree)
        observed.extend(visitor.observed)
    return sorted(observed, key=lambda item: (item.key, item.line, item.expression))


def validate_inventory(
    observed: list[ObservedCallSite],
    reviewed: dict[CallSiteKey, ReviewedCallSite] = REVIEWED_CALL_SITES,
) -> list[str]:
    """Return fail-closed drift errors for observed versus reviewed authority."""

    observed_keys = [item.key for item in observed]
    errors: list[str] = []
    duplicates = sorted({key for key in observed_keys if observed_keys.count(key) > 1})
    for key in duplicates:
        errors.append(f"duplicate authority sink requires distinct scope: {key}")
    for item in observed:
        if item.key not in reviewed:
            errors.append(
                f"unreviewed authority sink: {item.key.path}:{item.line} "
                f"{item.key.scope} [{item.key.sink}] via {item.expression}"
            )
    for key in sorted(set(reviewed) - set(observed_keys)):
        errors.append(f"reviewed authority sink disappeared or moved without reconciliation: {key}")
    return errors


def _render_json(observed: list[ObservedCallSite]) -> str:
    rows: list[dict[str, object]] = []
    for item in observed:
        review = REVIEWED_CALL_SITES.get(item.key)
        row: dict[str, object] = {
            **asdict(item.key),
            "line": item.line,
            "expression": item.expression,
            "reviewed": review is not None,
        }
        if review is not None:
            row.update(asdict(review))
        rows.append(row)
    return json.dumps(rows, indent=2, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and validate production runtime-authority call sites.")
    parser.add_argument("--json", action="store_true", help="Print the reviewed machine-readable inventory.")
    args = parser.parse_args()

    observed = inventory_runtime_authority()
    errors = validate_inventory(observed)
    if args.json:
        print(_render_json(observed))
    else:
        classifications: dict[str, int] = {}
        for item in observed:
            review = REVIEWED_CALL_SITES.get(item.key)
            label = review.classification if review is not None else "unreviewed"
            classifications[label] = classifications.get(label, 0) + 1
        summary = ", ".join(f"{key}={value}" for key, value in sorted(classifications.items()))
        print(f"runtime authority sinks: total={len(observed)}; {summary}")

    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    if errors:
        return 1
    print("PASS: runtime authority inventory matches the reviewed implementation topology.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
