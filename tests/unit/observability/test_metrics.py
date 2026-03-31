from backend.observability.metrics import ObservabilityMetrics


def test_metrics_snapshot_shape() -> None:
    snapshot = ObservabilityMetrics().snapshot(
        tasks_queued=1,
        tasks_completed=2,
        tasks_failed=3,
        dead_letter_count=4,
        lease_expirations=5,
        active_leases=6,
        queued_tasks=7,
        worker_utilization=0.5,
    )
    assert snapshot.tasks_completed == 2
    assert snapshot.worker_utilization == 0.5
