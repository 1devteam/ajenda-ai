#!/usr/bin/env python3
"""Expose deployment support edges that source-import graphs cannot see.

The canonical Python graph can prove that a browser handler imports Playwright,
but it cannot prove that the worker image installs a compatible browser or that
startup checks the feature before claiming work.  This inventory keeps those
deployment facts explicit and source-backed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

BROWSER_ACTION = "web.browser_session"

CDE_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    (
        "deployment:cde-release-workflow",
        "deployment_release_workflow",
        ".github/workflows/release.yml",
        "release workflow",
    ),
    (
        "deployment:cde-compose-production",
        "deployment_compose",
        "deploy/compose/docker-compose.prod.yml",
        "production Compose",
    ),
    ("deployment:cde-ecs-module", "deployment_iac_module", "infra/modules/ecs/main.tf", "ECS task/service module"),
    (
        "deployment:cde-secrets-module",
        "deployment_iac_module",
        "infra/modules/secrets/main.tf",
        "ECS secrets policy module",
    ),
    (
        "deployment:cde-staging-root",
        "deployment_iac_environment",
        "infra/environments/staging/main.tf",
        "staging ECS root",
    ),
    (
        "deployment:cde-production-root",
        "deployment_iac_environment",
        "infra/environments/production/main.tf",
        "production ECS root",
    ),
    ("deployment:cde-promotion", "deployment_promotion_procedure", "deploy/scripts/ecs-promote.sh", "ECS promotion"),
    ("deployment:cde-rollback", "deployment_rollback_procedure", "deploy/scripts/ecs-rollback.sh", "ECS rollback"),
    (
        "deployment:cde-kubernetes-reference",
        "deployment_reference",
        "deploy/k8s/README.md",
        "Kubernetes reference status",
    ),
    (
        "deployment:cde-legacy-rollback",
        "deployment_reference",
        "deploy/scripts/rollback.sh",
        "legacy rollback boundary",
    ),
    ("deployment:cde-ecs-frontend", "deployment_iac_module", "infra/modules/ecs/frontend.tf", "ECS frontend module"),
    ("deployment:cde-ecs-outputs", "deployment_iac_module", "infra/modules/ecs/outputs.tf", "ECS task/service outputs"),
    ("deployment:cde-ecs-contract", "deployment_iac_module", "infra/modules/ecs/variables.tf", "ECS input contract"),
    (
        "deployment:cde-secrets-outputs",
        "deployment_iac_module",
        "infra/modules/secrets/outputs.tf",
        "secret policy outputs",
    ),
    (
        "deployment:cde-secrets-contract",
        "deployment_iac_module",
        "infra/modules/secrets/variables.tf",
        "secret policy input contract",
    ),
    ("deployment:cde-rds-module", "deployment_iac_module", "infra/modules/rds/main.tf", "RDS module"),
    ("deployment:cde-rds-outputs", "deployment_iac_module", "infra/modules/rds/outputs.tf", "RDS outputs"),
    ("deployment:cde-rds-contract", "deployment_iac_module", "infra/modules/rds/variables.tf", "RDS input contract"),
    ("deployment:cde-redis-module", "deployment_iac_module", "infra/modules/redis/main.tf", "Redis module"),
    (
        "deployment:cde-redis-contract",
        "deployment_iac_module",
        "infra/modules/redis/variables.tf",
        "Redis input contract",
    ),
    (
        "deployment:cde-staging-outputs",
        "deployment_iac_environment",
        "infra/environments/staging/outputs.tf",
        "staging promotion outputs",
    ),
    (
        "deployment:cde-staging-contract",
        "deployment_iac_environment",
        "infra/environments/staging/variables.tf",
        "staging input contract",
    ),
    (
        "deployment:cde-production-outputs",
        "deployment_iac_environment",
        "infra/environments/production/outputs.tf",
        "production promotion outputs",
    ),
    (
        "deployment:cde-production-contract",
        "deployment_iac_environment",
        "infra/environments/production/variables.tf",
        "production input contract",
    ),
    ("deployment:cde-readme", "deployment_documentation", "README.md", "deployment status overview"),
    (
        "deployment:cde-system-architecture",
        "deployment_documentation",
        "docs/architecture/SYSTEM_ARCHITECTURE.md",
        "system deployment architecture",
    ),
    (
        "deployment:cde-cloud-decision",
        "deployment_documentation",
        "docs/deployment/CLOUD_PLATFORM_DECISION_STUDY_2026-11-01.md",
        "cloud target decision",
    ),
    (
        "deployment:cde-production-contract-doc",
        "deployment_documentation",
        "docs/deployment/production-env-contract.md",
        "production environment contract",
    ),
    ("deployment:cde-infra-readme", "deployment_documentation", "infra/README.md", "infrastructure operator guide"),
    ("deployment:cde-promotion-runbook", "deployment_documentation", "ops/runbooks/deployment.md", "promotion runbook"),
    (
        "deployment:cde-staging-runbook",
        "deployment_documentation",
        "ops/runbooks/paid-customer-loop-staging.md",
        "staging proof runbook",
    ),
    ("deployment:cde-rollback-runbook", "deployment_documentation", "ops/runbooks/rollback.md", "rollback runbook"),
)


def _text(repo_root: Path, relative: str) -> str:
    path = repo_root / relative
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def collect_deployment_inventory(repo_root: Path) -> dict[str, Any]:
    """Return browser dependency, image, startup, and feature-gate facts."""

    pyproject_path = "pyproject.toml"
    worker_image_path = "deploy/docker/worker.Dockerfile"
    startup_path = "deploy/scripts/start-worker.sh"
    compose_path = "docker-compose.yml"
    config_path = "backend/app/config.py"
    browser_path = "backend/services/internet/browser_session.py"

    pyproject = _text(repo_root, pyproject_path)
    worker_image = _text(repo_root, worker_image_path)
    startup = _text(repo_root, startup_path)
    compose = _text(repo_root, compose_path)
    config = _text(repo_root, config_path)
    browser = _text(repo_root, browser_path)

    nodes = [
        {
            "id": "deployment:pyproject",
            "type": "deployment_dependency_manifest",
            "source": pyproject_path,
            "label": pyproject_path,
        },
        {
            "id": "deployment-browser:worker-image",
            "type": "deployment_image",
            "source": worker_image_path,
            "label": "worker image",
        },
        {
            "id": "deployment-browser:worker-startup",
            "type": "deployment_startup_check",
            "source": startup_path,
            "label": "worker startup",
        },
        {
            "id": "deployment-browser:compose",
            "type": "deployment_compose",
            "source": compose_path,
            "label": compose_path,
        },
        {
            "id": "dependency:playwright",
            "type": "runtime_dependency",
            "source": pyproject_path,
            "label": "Playwright",
        },
        {
            "id": "runtime-binary:chromium",
            "type": "runtime_binary",
            "source": worker_image_path,
            "label": "Chromium",
        },
        {
            "id": "config:browser-session-flag",
            "type": "runtime_feature_flag",
            "source": config_path,
            "label": "AJENDA_BROWSER_SESSION_ENABLED",
        },
    ]
    nodes.extend(
        {"id": node_id, "type": node_type, "source": source, "label": label}
        for node_id, node_type, source, label in CDE_SOURCES
    )
    edges = [
        {
            "from": f"action:{BROWSER_ACTION}",
            "to": "dependency:playwright",
            "type": "requires_runtime_dependency",
            "evidence": pyproject_path,
        },
        {
            "from": "dependency:playwright",
            "to": "deployment:pyproject",
            "type": "declared_in",
            "evidence": pyproject_path,
        },
        {
            "from": "dependency:playwright",
            "to": "deployment-browser:worker-image",
            "type": "installed_in",
            "evidence": worker_image_path,
        },
        {
            "from": "runtime-binary:chromium",
            "to": "deployment-browser:worker-image",
            "type": "installed_in",
            "evidence": worker_image_path,
        },
        {
            "from": "deployment-browser:worker-image",
            "to": "runtime:worker",
            "type": "provides_runtime_support",
            "evidence": worker_image_path,
        },
        {
            "from": "deployment-browser:worker-startup",
            "to": "runtime:worker",
            "type": "guards_startup",
            "evidence": startup_path,
        },
        {
            "from": f"action:{BROWSER_ACTION}",
            "to": "config:browser-session-flag",
            "type": "gated_by",
            "evidence": browser_path,
        },
        {
            "from": "config:browser-session-flag",
            "to": "deployment-browser:worker-startup",
            "type": "validated_by",
            "evidence": startup_path,
        },
        {
            "from": "config:browser-session-flag",
            "to": "deployment-browser:compose",
            "type": "injected_by_env_file",
            "evidence": compose_path,
        },
        {
            "from": "deployment:cde-release-workflow",
            "to": "deployment:cde-promotion",
            "type": "supplies_immutable_artifact_contract",
            "evidence": ".github/workflows/release.yml",
        },
        {
            "from": "deployment:cde-promotion",
            "to": "deployment:cde-ecs-module",
            "type": "promotes_declared_task_definitions",
            "evidence": "deploy/scripts/ecs-promote.sh",
        },
        {
            "from": "deployment:cde-promotion",
            "to": "deployment:cde-secrets-module",
            "type": "requires_external_secret_references",
            "evidence": "deploy/scripts/ecs-promote.sh",
        },
        {
            "from": "deployment:cde-promotion",
            "to": "runtime:api",
            "type": "starts_after_migration",
            "evidence": "deploy/scripts/ecs-promote.sh",
        },
        {
            "from": "deployment:cde-promotion",
            "to": "runtime:worker",
            "type": "starts_after_migration",
            "evidence": "deploy/scripts/ecs-promote.sh",
        },
        {
            "from": "deployment:cde-rollback",
            "to": "deployment:cde-ecs-module",
            "type": "changes_service_revision_only",
            "evidence": "deploy/scripts/ecs-rollback.sh",
        },
        {
            "from": "deployment:cde-staging-root",
            "to": "deployment:cde-ecs-module",
            "type": "configures_runtime_target",
            "evidence": "infra/environments/staging/main.tf",
        },
        {
            "from": "deployment:cde-production-root",
            "to": "deployment:cde-ecs-module",
            "type": "configures_runtime_target",
            "evidence": "infra/environments/production/main.tf",
        },
        {
            "from": "deployment:cde-staging-root",
            "to": "deployment:cde-secrets-module",
            "type": "references_runtime_secrets",
            "evidence": "infra/environments/staging/main.tf",
        },
        {
            "from": "deployment:cde-production-root",
            "to": "deployment:cde-secrets-module",
            "type": "references_runtime_secrets",
            "evidence": "infra/environments/production/main.tf",
        },
    ]

    findings: list[dict[str, Any]] = []
    checks = (
        ("playwright_dependency_missing", "playwright==", pyproject, pyproject_path),
        ("chromium_install_missing", "playwright install --with-deps chromium", worker_image, worker_image_path),
        ("browser_readiness_check_missing", "assert_browser_runtime_ready", startup, startup_path),
        ("browser_flag_missing", "AJENDA_BROWSER_SESSION_ENABLED", config, config_path),
        ("browser_gate_missing", "browser_session_enabled", browser, browser_path),
    )
    for finding_id, marker, content, evidence in checks:
        if marker in content:
            continue
        findings.append(
            {
                "id": f"deployment-browser:{finding_id}",
                "category": "deployment-runtime",
                "severity": "high",
                "summary": f"Browser runtime support is not source-proven by {evidence}: missing {marker!r}.",
                "evidence": [evidence],
                "related_nodes": ["action:web.browser_session", "runtime:worker"],
                "blocking": True,
                "classification": "deployment_support_gap",
            }
        )
    unknowns: list[dict[str, Any]] = []
    if "AJENDA_BROWSER_SESSION_ENABLED" not in compose:
        unknowns.append(
            {
                "id": "deployment-browser:flag-value-externalized",
                "classification": "deployment_configuration_unknown",
                "summary": (
                    "Compose loads browser enablement from an external env file; its value is not source-proven "
                    "by docker-compose.yml."
                ),
                "evidence": [compose_path],
                "related_nodes": ["config:browser-session-flag", "deployment-browser:compose"],
                "blocking": False,
            }
        )
    return {
        "nodes": nodes,
        "edges": edges,
        "findings": findings,
        "unknowns": unknowns,
        "metrics": {
            "deployment_node_count": len(nodes),
            "deployment_edge_count": len(edges),
            "deployment_finding_count": len(findings),
            "deployment_unknown_count": len(unknowns),
            "cde_node_count": len(CDE_SOURCES),
        },
    }
