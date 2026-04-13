from backend.services.runtime_maintainer import RecoverySummary


def test_recovery_trigger_contract() -> None:
    summary = RecoverySummary(
        expired_lease_count=0,
        requeued_task_count=0,
        dead_lettered_count=0,
    )
    assert summary.requeued_task_count == 0
    assert summary.dead_lettered_count == 0
