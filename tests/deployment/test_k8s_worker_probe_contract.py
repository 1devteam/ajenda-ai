"""Drift guards for Kubernetes worker probes and worker liveness file behavior."""

from __future__ import annotations

from pathlib import Path

WORKER_DEPLOYMENT = Path("deploy/k8s/worker-deployment.yaml")
WORKER_LOOP = Path("backend/workers/worker_loop.py")

EXPECTED_LIVENESS_FILE = "/tmp/worker-alive"
EXPECTED_LIVENESS_UPDATE_INTERVAL_SECONDS = "10.0"
EXPECTED_STALE_LIVENESS_THRESHOLD_SECONDS = "60"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_worker_loop_owns_liveness_file_path_and_update_interval() -> None:
    worker_loop = _read(WORKER_LOOP)

    assert f'_LIVENESS_FILE = Path("{EXPECTED_LIVENESS_FILE}")' in worker_loop
    assert f"_LIVENESS_UPDATE_INTERVAL = {EXPECTED_LIVENESS_UPDATE_INTERVAL_SECONDS}" in worker_loop
    assert "self._touch_liveness()" in worker_loop
    assert "self._maybe_touch_liveness()" in worker_loop


def test_worker_deployment_uses_exec_probes_not_http_probes() -> None:
    deployment = _read(WORKER_DEPLOYMENT)

    assert "livenessProbe:" in deployment
    assert "readinessProbe:" in deployment
    assert "exec:" in deployment
    assert "httpGet:" not in deployment
    assert "localhost:8000" not in deployment
    assert "port: 8000" not in deployment


def test_worker_liveness_probe_checks_fresh_liveness_file() -> None:
    deployment = _read(WORKER_DEPLOYMENT)

    assert f"test -f {EXPECTED_LIVENESS_FILE}" in deployment
    assert "stat -c %Y" in deployment
    assert f"-lt {EXPECTED_STALE_LIVENESS_THRESHOLD_SECONDS}" in deployment


def test_worker_readiness_probe_checks_liveness_file_exists() -> None:
    deployment = _read(WORKER_DEPLOYMENT)

    assert f'"test -f {EXPECTED_LIVENESS_FILE}"' in deployment


def test_worker_probe_timing_matches_liveness_update_contract() -> None:
    deployment = _read(WORKER_DEPLOYMENT)

    assert "initialDelaySeconds: 30" in deployment
    assert "periodSeconds: 20" in deployment
    assert "failureThreshold: 3" in deployment
    assert "timeoutSeconds: 5" in deployment
    assert "initialDelaySeconds: 10" in deployment
    assert "periodSeconds: 15" in deployment
    assert "failureThreshold: 2" in deployment
