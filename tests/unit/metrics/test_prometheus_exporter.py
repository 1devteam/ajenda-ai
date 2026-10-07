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


def test_prometheus_exporter_renders_stage_budget_metric_labels_and_values() -> None:
    snapshot = MetricsSnapshot(
        tasks_queued=1,
        tasks_completed=2,
        tasks_failed=3,
        dead_letter_count=4,
        lease_expirations=5,
        active_leases=6,
        queued_tasks=7,
        worker_utilization=0.5,
        stage_budget_limit_cost_usd=100.25,
        stage_budget_spend_cost_usd=75.5,
        stage_budget_limit_runtime_minutes=60.0,
        stage_budget_spend_runtime_minutes=42.75,
        stage_budget_breach_total=3,
    )

    output = PrometheusExporter().render(snapshot)

    assert 'ajenda_stage_budget_limit{stage="runtime",budget_kind="cost_usd"} 100.25' in output
    assert 'ajenda_stage_budget_limit{stage="runtime",budget_kind="runtime_minutes"} 60.0' in output
    assert 'ajenda_stage_budget_spend{stage="runtime",budget_kind="cost_usd"} 75.5' in output
    assert 'ajenda_stage_budget_spend{stage="runtime",budget_kind="runtime_minutes"} 42.75' in output
    assert 'ajenda_stage_budget_breach_total{stage="runtime",budget_kind="any"} 3' in output


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


def test_prometheus_exporter_renders_tenant_label_when_provided() -> None:
    snapshot = MetricsSnapshot(1, 2, 3, 4, 5, 6, 7, 0.5, tenant_id="tenant-123")
    output = PrometheusExporter().render(snapshot)
    assert 'ajenda_tasks_queued{tenant_id="tenant-123"} 1' in output
    assert 'ajenda_active_leases{tenant_id="tenant-123"} 6' in output
    # stage labels merged
    assert 'ajenda_stage_budget_limit{stage="runtime",budget_kind="cost_usd",tenant_id="tenant-123"}' in output
    # banned tenant_id is allowed intentionally for per-tenant
    assert 'tenant_id="tenant-123"' in output


def test_assurance_metrics_are_exported() -> None:
    snapshot = MetricsSnapshot(
        tasks_queued=0,
        tasks_completed=1,
        tasks_failed=0,
        dead_letter_count=0,
        lease_expirations=0,
        active_leases=0,
        queued_tasks=0,
        worker_utilization=0.0,
        assurance_snapshot_count=4,
        assurance_incomplete_count=1,
        assurance_drifted_count=2,
        assurance_contradictory_count=1,
        assurance_first_divergence_count=1,
        assurance_calibration_sample_count=3,
        assurance_calibration_aligned_count=2,
        assurance_tenant_failure_count=1,
    )
    rendered = PrometheusExporter().render(snapshot)

    assert "ajenda_assurance_snapshot_count 4" in rendered
    assert "ajenda_assurance_incomplete_count 1" in rendered
    assert "ajenda_assurance_drifted_count 2" in rendered
    assert "ajenda_assurance_contradictory_count 1" in rendered
    assert "ajenda_assurance_first_divergence_count 1" in rendered
    assert "ajenda_assurance_calibration_sample_count 3" in rendered
    assert "ajenda_assurance_calibration_aligned_count 2" in rendered
    assert "ajenda_assurance_tenant_failure_count 1" in rendered
