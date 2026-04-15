from backend.services.retry_policy import RetryPolicy


def test_retry_behavior_terminal_after_limit() -> None:
    decision = RetryPolicy(max_attempts=2, base_delay_seconds=1).evaluate(attempt_number=2, terminal_failure=False)
    assert decision.retry is False
    assert decision.terminal is True
