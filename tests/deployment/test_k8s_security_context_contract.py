"""Drift guards for Kubernetes deployment security contexts."""

from __future__ import annotations

from pathlib import Path

API_DEPLOYMENT = Path("deploy/k8s/api-deployment.yaml")
WORKER_DEPLOYMENT = Path("deploy/k8s/worker-deployment.yaml")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block_after_marker(text: str, marker: str) -> str:
    marker_index = text.index(marker)
    return text[marker_index:]


def test_worker_container_security_context_blocks_privilege_escalation() -> None:
    worker = _read(WORKER_DEPLOYMENT)
    security_context = _block_after_marker(worker, "securityContext:")

    assert "allowPrivilegeEscalation: false" in security_context
    assert "runAsNonRoot: true" in security_context
    assert "runAsUser: 1000" in security_context


def test_worker_container_drops_linux_capabilities() -> None:
    worker = _read(WORKER_DEPLOYMENT)
    security_context = _block_after_marker(worker, "securityContext:")

    assert "capabilities:" in security_context
    assert "drop:" in security_context
    assert "- ALL" in security_context


def test_worker_pod_security_context_sets_filesystem_group() -> None:
    worker = _read(WORKER_DEPLOYMENT)

    assert "securityContext:" in worker
    assert "fsGroup: 1000" in worker


def test_worker_root_filesystem_setting_stays_explicit() -> None:
    worker = _read(WORKER_DEPLOYMENT)

    assert "readOnlyRootFilesystem: false" in worker


def test_api_deployment_does_not_accidentally_gain_privileged_flags() -> None:
    api = _read(API_DEPLOYMENT)

    assert "privileged: true" not in api
    assert "allowPrivilegeEscalation: true" not in api
    assert "runAsUser: 0" not in api


def test_worker_deployment_does_not_use_privileged_or_root_user() -> None:
    worker = _read(WORKER_DEPLOYMENT)

    assert "privileged: true" not in worker
    assert "allowPrivilegeEscalation: true" not in worker
    assert "runAsUser: 0" not in worker
