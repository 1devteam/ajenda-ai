from backend.metrics.prometheus_exporter import PrometheusExporter
from backend.observability.metrics import MetricsSnapshot


def test_prometheus_exporter_renders_required_gauge_types() -> None:
    output = PrometheusExporter().render(MetricsSnapshot(1, 2, 3, 4, 5, 6, 7, 0.5))

    assert "# TYPE ajenda_active_leases gauge" in output
    assert "# TYPE ajenda_dead_letter_count gauge" in output
    assert "# TYPE ajenda_worker_utilization gauge" in output
    assert "# TYPE ajenda_queue_depth gauge" in output
    assert "# TYPE ajenda_stage_budget_limit gauge" in output
    assert "# TYPE ajenda_stage_budget_spend gauge" in output
    assert "# TYPE ajenda_stage_budget_breach_total counter" in output
    assert "# TYPE ajenda_stale_leases gauge" not in output


def test_prometheus_exporter_does_not_emit_banned_labels() -> None:
    output = PrometheusExporter().render(MetricsSnapshot(1, 2, 3, 4, 5, 6, 7, 0.5))
    banned_tokens = (
        "tenant",
        "task",
        "worker_id",
        "mission",
        "hostname",
        "exception",
        "traceback",
        "url",
        "password",
        "token",
        "secret",
    )

    for line in output.splitlines():
        if "{" not in line:
            continue
        for token in banned_tokens:
            assert token not in line
