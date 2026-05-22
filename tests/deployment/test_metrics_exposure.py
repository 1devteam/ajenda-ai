from pathlib import Path


def test_metrics_scrape_path_is_exposed() -> None:
    """The ServiceMonitor must reference the correct versioned path.

    The observability router is mounted under /v1/ by build_api_router(),
    so the full scrape path is /v1/observability/metrics, not /observability/metrics.
    """
    content = Path("deploy/k8s/prometheus-servicemonitor.yaml").read_text(encoding="utf-8")
    assert "/v1/observability/metrics" in content


def test_compose_prometheus_uses_versioned_observability_metrics_path() -> None:
    content = Path("deploy/compose/prometheus.yml").read_text(encoding="utf-8")
    assert "metrics_path: /v1/observability/metrics" in content
    assert "metrics_path: /metrics" not in content
