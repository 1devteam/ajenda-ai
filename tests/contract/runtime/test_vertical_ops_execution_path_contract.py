"""Contract: vertical-ops queues only through VerticalOpsTemplateService → ExecutionCoordinator."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ROUTE_PATH = REPO_ROOT / "backend/api/routes/vertical_ops.py"
SERVICE_PATH = REPO_ROOT / "backend/services/vertical_ops/template_service.py"

FORBIDDEN_MODULES = {
    "backend.workers.task_dispatcher",
    "backend.workers.worker_loop",
    "celery",
    "backend.services.agent_swarm",
}


def _imported_modules(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_vertical_ops_route_does_not_import_dispatcher_or_worker_loop() -> None:
    imported = _imported_modules(ROUTE_PATH)
    for forbidden in FORBIDDEN_MODULES:
        assert not any(item == forbidden or item.startswith(f"{forbidden}.") for item in imported)


def test_vertical_ops_queue_path_uses_template_service_not_direct_dispatcher() -> None:
    source = ROUTE_PATH.read_text(encoding="utf-8")
    assert "VerticalOpsTemplateService" in source
    assert "queue_planned_tasks" in source or "apply_and_queue" in source
    imported = _imported_modules(ROUTE_PATH)
    assert "backend.workers.task_dispatcher" not in imported


def test_template_service_queue_uses_execution_coordinator_only() -> None:
    source = SERVICE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "queue_planned_tasks":
            segment = ast.get_source_segment(source, node) or ""
            assert "ExecutionCoordinator" in segment
            assert ".queue_task(" in segment
            found = True
    assert found
    imported = _imported_modules(SERVICE_PATH)
    assert "backend.workers.task_dispatcher" not in imported
    assert "backend.workers.worker_loop" not in imported
    assert not any("agent_swarm" in item for item in imported)
