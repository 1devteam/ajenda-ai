from backend.metrics.prometheus_exporter import PrometheusExporter
from backend.observability.metrics import MetricsSnapshot


def test_metrics_endpoint_contract_smoke() -> None:
    rendered = PrometheusExporter().render(MetricsSnapshot(0, 0, 0, 0, 0, 0, 0, 0.0))
    assert "ajenda_tasks_queued 0" in rendered
