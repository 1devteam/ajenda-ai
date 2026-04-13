from backend.services.runtime_maintainer import RecoverySummary


def test_recovery_summary_shape() -> None:
    summary = RecoverySummary(
        expired_lease_count=1,
        requeued_task_count=1,
        dead_lettered_count=0,
    )
    assert summary.expired_lease_count == 1
    assert summary.requeued_task_count == 1
    assert summary.dead_lettered_count == 0
