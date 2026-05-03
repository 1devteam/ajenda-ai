"""Drift guards for Kubernetes deployment security contexts."""

from __future__ import annotations

from pathlib import Path

API_DEPLOYMENT = Path("deploy/k8s/api-deployment.yaml")
WORKER_DEPLOYMENT = Path("deploy/k8s/worker-deployment.yaml")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _non_comment_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def _indented_block(lines: list[str], marker: str, *, start_at: int = 0) -> list[str]:
    for index in range(start_at, len(lines)):
        line = lines[index]
        if line.strip() != marker:
            continue
        marker_indent = len(line) - len(line.lstrip())
        block: list[str] = []
        for candidate in lines[index + 1 :]:
            if not candidate.strip():
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if candidate_indent <= marker_indent:
                break
            block.append(candidate)
        return block
    raise AssertionError(f"missing YAML block marker: {marker}")


def _container_security_context_lines(deployment_path: Path) -> list[str]:
    lines = _non_comment_lines(_read(deployment_path))
    containers_block = _indented_block(lines, "containers:")
    return _indented_block(containers_block, "securityContext:")


def _pod_security_context_lines(deployment_path: Path) -> list[str]:
    lines = _non_comment_lines(_read(deployment_path))
    container_security_context_index = next(
        index
        for index, line in enumerate(lines)
        if line.strip() == "securityContext:" and line.startswith("          ")
    )
    return _indented_block(lines, "securityContext:", start_at=container_security_context_index + 1)


def _normalized_values(lines: list[str]) -> set[str]:
    return {line.strip() for line in lines}


def test_worker_container_security_context_blocks_privilege_escalation() -> None:
    security_context = _normalized_values(_container_security_context_lines(WORKER_DEPLOYMENT))

    assert "allowPrivilegeEscalation: false" in security_context
    assert "runAsNonRoot: true" in security_context
    assert "runAsUser: 1000" in security_context


def test_worker_container_drops_linux_capabilities() -> None:
    security_context = _normalized_values(_container_security_context_lines(WORKER_DEPLOYMENT))

    assert "capabilities:" in security_context
    assert "drop:" in security_context
    assert "- ALL" in security_context


def test_worker_pod_security_context_sets_filesystem_group() -> None:
    pod_security_context = _normalized_values(_pod_security_context_lines(WORKER_DEPLOYMENT))

    assert "fsGroup: 1000" in pod_security_context


def test_worker_root_filesystem_setting_stays_explicit() -> None:
    security_context = _normalized_values(_container_security_context_lines(WORKER_DEPLOYMENT))

    assert "readOnlyRootFilesystem: false" in security_context


def test_api_container_security_context_blocks_privilege_escalation() -> None:
    security_context = _normalized_values(_container_security_context_lines(API_DEPLOYMENT))

    assert "allowPrivilegeEscalation: false" in security_context
    assert "runAsNonRoot: true" in security_context
    assert "runAsUser: 1000" in security_context


def test_api_container_drops_linux_capabilities() -> None:
    security_context = _normalized_values(_container_security_context_lines(API_DEPLOYMENT))

    assert "capabilities:" in security_context
    assert "drop:" in security_context
    assert "- ALL" in security_context


def test_api_pod_security_context_sets_filesystem_group() -> None:
    pod_security_context = _normalized_values(_pod_security_context_lines(API_DEPLOYMENT))

    assert "fsGroup: 1000" in pod_security_context


def test_api_root_filesystem_setting_stays_explicit() -> None:
    security_context = _normalized_values(_container_security_context_lines(API_DEPLOYMENT))

    assert "readOnlyRootFilesystem: false" in security_context


def test_api_deployment_does_not_accidentally_gain_privileged_flags() -> None:
    api = "\n".join(_non_comment_lines(_read(API_DEPLOYMENT)))

    assert "privileged: true" not in api
    assert "allowPrivilegeEscalation: true" not in api
    assert "runAsUser: 0" not in api


def test_worker_deployment_does_not_use_privileged_or_root_user() -> None:
    worker = "\n".join(_non_comment_lines(_read(WORKER_DEPLOYMENT)))

    assert "privileged: true" not in worker
    assert "allowPrivilegeEscalation: true" not in worker
    assert "runAsUser: 0" not in worker
