#!/usr/bin/env python3
"""Derive source-backed deployment/runtime support contracts for G.R.A.F.T.

This inventory keeps runtime action placement tied to the deployment surfaces
that make the action executable. It is diagnostic only: it never grants runtime
authority and it does not infer deployment support from Python imports alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PYPROJECT_PATH = Path("pyproject.toml")
WORKER_DOCKERFILE_PATH = Path("deploy/docker/worker.Dockerfile")
WORKER_STARTUP_PATH = Path("deploy/scripts/start-worker.sh")
COMPOSE_PATH = Path("deploy/compose/docker-compose.prod.yml")


def _rel(path: Path) -> str:
    return str(path).replace("\\", "/")


def _contains(repo_root: Path, path: Path, marker: str) -> bool:
    full = repo_root / path
    if not full.exists():
        return False
    try:
        return marker in full.read_text(encoding="utf-8")
    except OSError:
        return False


def collect_runtime_support_inventory(repo_root: Path) -> dict[str, Any]:
    """Return deployment support nodes, edges, findings, and metrics."""

    action_id = "action:web.browser_session"
    support_id = "runtime-support:web.browser_session"
    surfaces = (
        (
            "deployment:python-project",
            PYPROJECT_PATH,
            "playwright==",
            "declared_dependency",
            "Python dependency declaration",
        ),
        (
            "deployment:worker-image",
            WORKER_DOCKERFILE_PATH,
            "playwright install --with-deps chromium",
            "installed_by",
            "worker Chromium installation",
        ),
        (
            "deployment:worker-startup",
            WORKER_STARTUP_PATH,
            "assert_browser_runtime_ready()",
            "validated_by",
            "worker browser-readiness assertion",
        ),
        (
            "deployment:prod-compose",
            COMPOSE_PATH,
            "dockerfile: deploy/docker/worker.Dockerfile",
            "deployed_by",
            "production Compose worker image binding",
        ),
    )

    nodes: list[dict[str, Any]] = [
        {
            "id": support_id,
            "type": "runtime_support",
            "source": _rel(WORKER_STARTUP_PATH),
            "label": "web.browser_session deployment/runtime support",
            "grants_execution_authority": False,
        }
    ]
    edges: list[dict[str, Any]] = [
        {
            "from": action_id,
            "to": support_id,
            "type": "requires_runtime_support",
            "evidence": _rel(WORKER_STARTUP_PATH),
        }
    ]
    findings: list[dict[str, Any]] = []
    satisfied = 0

    for node_id, path, marker, edge_type, label in surfaces:
        present = _contains(repo_root, path, marker)
        nodes.append(
            {
                "id": node_id,
                "type": "deployment_surface",
                "source": _rel(path),
                "label": label,
                "support_present": present,
            }
        )
        edges.append(
            {
                "from": support_id,
                "to": node_id,
                "type": edge_type,
                "evidence": _rel(path),
            }
        )
        if present:
            satisfied += 1
            continue
        findings.append(
            {
                "id": f"runtime-support-missing:web.browser_session:{node_id.split(':', 1)[1]}",
                "category": "runtime-deployment-support",
                "severity": "high",
                "summary": (
                    f"web.browser_session is runtime-declared but required deployment support is missing: {label}."
                ),
                "evidence": [_rel(path)],
                "related_nodes": [action_id, support_id, node_id],
                "blocking": True,
                "classification": "runtime_support_missing",
            }
        )

    return {
        "nodes": sorted(nodes, key=lambda item: str(item["id"])),
        "edges": sorted(edges, key=lambda item: (str(item["from"]), str(item["to"]), str(item["type"]))),
        "findings": sorted(findings, key=lambda item: str(item["id"])),
        "metrics": {
            "support_contract_count": 1,
            "deployment_surface_count": len(surfaces),
            "satisfied_surface_count": satisfied,
            "missing_surface_count": len(surfaces) - satisfied,
        },
    }
