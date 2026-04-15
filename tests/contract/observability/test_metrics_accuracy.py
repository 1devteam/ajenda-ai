from backend.observability.metrics import ObservabilityMetrics


def test_metrics_accuracy_smoke() -> None:
    snapshot = ObservabilityMetrics().snapshot(
        tasks_queued=0,
        tasks_completed=1,
        tasks_failed=0,
        dead_letter_count=0,
        lease_expirations=0,
        active_leases=1,
        queued_tasks=0,
        worker_utilization=1.0,
    )
    assert snapshot.active_leases == 1
