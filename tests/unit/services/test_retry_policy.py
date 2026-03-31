from backend.services.retry_policy import RetryPolicy


def test_retry_policy_retries_before_limit() -> None:
    decision = RetryPolicy(max_attempts=3, base_delay_seconds=5).evaluate(attempt_number=1, terminal_failure=False)
    assert decision.retry is True
    assert decision.delay_seconds == 5
