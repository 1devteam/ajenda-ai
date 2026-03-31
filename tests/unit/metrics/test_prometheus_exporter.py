from backend.metrics.prometheus_exporter import PrometheusExporter
from backend.observability.metrics import MetricsSnapshot


def test_prometheus_exporter_renders_metrics() -> None:
    output = PrometheusExporter().render(MetricsSnapshot(1, 2, 3, 4, 5, 6, 7, 0.5))
    assert "ajenda_tasks_completed 2" in output
