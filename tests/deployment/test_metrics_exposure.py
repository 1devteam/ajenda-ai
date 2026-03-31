from pathlib import Path


def test_metrics_scrape_path_is_exposed() -> None:
    content = Path("deploy/k8s/prometheus-servicemonitor.yaml").read_text(encoding="utf-8")
    assert "/observability/metrics" in content
