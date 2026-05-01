"""Drift guards for Kubernetes observability scrape configuration.

These tests keep Kubernetes ServiceMonitor scraping aligned with the Compose
Prometheus scrape config and the API Service port wiring. They validate static
manifests only; live scraping is proved by deploy/scripts/live-runtime-proof.sh.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PROMETHEUS = REPO_ROOT / "deploy" / "compose" / "prometheus.yml"
K8S_SERVICE_MONITOR = REPO_ROOT / "deploy" / "k8s" / "prometheus-servicemonitor.yaml"
K8S_API_SERVICE = REPO_ROOT / "deploy" / "k8s" / "api-service.yaml"

EXPECTED_METRICS_PATH = "/v1/observability/metrics"
EXPECTED_JOB_NAME = "ajenda-api"
EXPECTED_SERVICE_PORT_NAME = "http"
EXPECTED_API_TARGET_PORT = "8000"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _yaml_scalar(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*-?\s*{re.escape(key)}:\s*[\"']?(?P<value>[^\"'\n]+)[\"']?\s*$", text, flags=re.MULTILINE)
    if match is None:
        return None
    return match.group("value").strip()


def _api_service_port_block(api_service: str) -> str:
    match = re.search(
        r"^  ports:\n(?P<body>(?:^    - .*\n|^      .+\n)+)",
        api_service,
        flags=re.MULTILINE,
    )
    assert match is not None, "api-service.yaml must define spec.ports"
    return match.group("body")


def test_compose_prometheus_uses_versioned_observability_metrics_path() -> None:
    compose_prometheus = _read(COMPOSE_PROMETHEUS)

    assert f"metrics_path: {EXPECTED_METRICS_PATH}" in compose_prometheus
    assert f"job_name: {EXPECTED_JOB_NAME}" in compose_prometheus


def test_k8s_service_monitor_uses_same_metrics_path_as_compose_prometheus() -> None:
    compose_prometheus = _read(COMPOSE_PROMETHEUS)
    service_monitor = _read(K8S_SERVICE_MONITOR)

    compose_metrics_path = _yaml_scalar(compose_prometheus, "metrics_path")
    service_monitor_path = _yaml_scalar(service_monitor, "path")

    assert compose_metrics_path == EXPECTED_METRICS_PATH
    assert service_monitor_path == compose_metrics_path


def test_k8s_service_monitor_targets_api_http_service_port() -> None:
    service_monitor = _read(K8S_SERVICE_MONITOR)
    api_service_port_block = _api_service_port_block(_read(K8S_API_SERVICE))

    service_monitor_port = _yaml_scalar(service_monitor, "port")
    api_service_port_name = _yaml_scalar(api_service_port_block, "name")

    assert service_monitor_port == EXPECTED_SERVICE_PORT_NAME
    assert api_service_port_name == service_monitor_port


def test_k8s_api_service_exposes_expected_api_target_port() -> None:
    api_service_port_block = _api_service_port_block(_read(K8S_API_SERVICE))

    assert _yaml_scalar(api_service_port_block, "targetPort") == EXPECTED_API_TARGET_PORT


def test_k8s_service_monitor_selects_ajenda_api_service() -> None:
    service_monitor = _read(K8S_SERVICE_MONITOR)
    api_service = _read(K8S_API_SERVICE)

    assert "name: ajenda-api" in service_monitor
    assert "app: ajenda-api" in service_monitor
    assert "name: ajenda-api" in api_service
    assert "app: ajenda-api" in api_service
