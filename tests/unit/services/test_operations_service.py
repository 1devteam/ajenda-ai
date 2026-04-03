from backend.services.runtime_maintainer import RecoverySummary


def test_recovery_summary_contract() -> None:
    """RecoverySummary captures all three outcome counts from a recovery cycle."""
    summary = RecoverySummary(
        expired_lease_count=2,
        requeued_task_count=1,
        dead_lettered_count=1,
    )
    assert summary.expired_lease_count == 2
    assert summary.requeued_task_count == 1
    assert summary.dead_lettered_count == 1
