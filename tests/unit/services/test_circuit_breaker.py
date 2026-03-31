from backend.services.circuit_breaker import CircuitBreaker


def test_circuit_breaker_opens_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=2)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow() is False
