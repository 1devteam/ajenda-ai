from pathlib import Path


def test_metrics_scrape_path_is_exposed() -> None:
    """The ServiceMonitor must reference the correct versioned path.

    The observability router is mounted under /v1/ by build_api_router(),
    so the full scrape path is /v1/observability/metrics, not /observability/metrics.
    """
    content = Path("deploy/k8s/prometheus-servicemonitor.yaml").read_text(encoding="utf-8")
    assert "/v1/observability/metrics" in content
