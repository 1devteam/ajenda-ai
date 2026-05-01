"""Drift guards for the Kubernetes rollback script."""

from __future__ import annotations

from pathlib import Path

ROLLBACK_SCRIPT = Path("deploy/scripts/rollback.sh")


def _read() -> str:
    return ROLLBACK_SCRIPT.read_text(encoding="utf-8")


def test_rollback_script_uses_safe_shell_flags() -> None:
    script = _read()

    assert script.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in script


def test_rollback_script_supports_namespace_and_revision_arguments() -> None:
    script = _read()

    assert "NAMESPACE=\"ajenda\"" in script
    assert "REVISION=\"\"" in script
    assert "--namespace|-n" in script
    assert "--revision|-r" in script
    assert "Unknown argument" in script


def test_rollback_script_checks_cluster_reachability_before_mutation() -> None:
    script = _read()

    cluster_info_index = script.index("kubectl cluster-info")
    first_undo_index = script.index("kubectl rollout undo")

    assert cluster_info_index < first_undo_index
    assert "ERROR: Cannot reach Kubernetes cluster" in script


def test_rollback_script_rolls_back_api_and_worker_deployments() -> None:
    script = _read()

    assert "kubectl rollout undo deployment/ajenda-api" in script
    assert "kubectl rollout undo deployment/ajenda-worker" in script
    assert "${ROLLBACK_ARGS[@]}" in script


def test_rollback_script_waits_for_rollout_completion() -> None:
    script = _read()

    assert "kubectl rollout status deployment/ajenda-api" in script
    assert "kubectl rollout status deployment/ajenda-worker" in script
    assert "--timeout=120s" in script


def test_rollback_script_reports_pre_and_post_rollback_state() -> None:
    script = _read()

    assert "kubectl rollout history deployment/ajenda-api" in script
    assert "kubectl rollout history deployment/ajenda-worker" in script
    assert "kubectl get pods" in script
    assert "app in (ajenda-api,ajenda-worker)" in script
