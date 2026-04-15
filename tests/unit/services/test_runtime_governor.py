from __future__ import annotations

from types import SimpleNamespace

from backend.services.runtime_governor import RuntimeDecision, RuntimeGovernor, RuntimeMode


def test_evaluate_returns_normal_when_continuity_floor_met(monkeypatch) -> None:
    class _FakeHealthChecker:
        def __init__(self, session) -> None:
            self.session = session

        def assess_foundation_health(self):
            return SimpleNamespace(continuity_floor_met=True, failure_reason=None)

    monkeypatch.setattr("backend.services.runtime_governor.FoundationHealthChecker", _FakeHealthChecker)

    decision = RuntimeGovernor(session=object()).evaluate()

    assert decision == RuntimeDecision(
        mode=RuntimeMode.NORMAL,
        provisioning_allowed=True,
        execution_allowed=True,
        reason="All dependencies healthy. Normal execution permitted.",
    )


def test_evaluate_returns_degraded_when_continuity_floor_not_met(monkeypatch) -> None:
    class _FakeHealthChecker:
        def __init__(self, session) -> None:
            self.session = session

        def assess_foundation_health(self):
            return SimpleNamespace(
                continuity_floor_met=False,
                failure_reason="redis unavailable",
            )

    monkeypatch.setattr("backend.services.runtime_governor.FoundationHealthChecker", _FakeHealthChecker)

    decision = RuntimeGovernor(session=object()).evaluate()

    assert decision.mode is RuntimeMode.DEGRADED
    assert decision.provisioning_allowed is False
    assert decision.execution_allowed is True
    assert decision.reason == "Dependency health degraded below continuity floor. New provisioning blocked."


def test_evaluate_returns_degraded_when_health_check_raises(monkeypatch) -> None:
    class _FakeHealthChecker:
        def __init__(self, session) -> None:
            self.session = session

        def assess_foundation_health(self):
            raise RuntimeError("boom")

    monkeypatch.setattr("backend.services.runtime_governor.FoundationHealthChecker", _FakeHealthChecker)

    decision = RuntimeGovernor(session=object()).evaluate()

    assert decision.mode is RuntimeMode.DEGRADED
    assert decision.provisioning_allowed is False
    assert decision.execution_allowed is True
    assert "Health check failed" in decision.reason
    assert "boom" in decision.reason


def test_force_restricted_returns_restricted_decision() -> None:
    governor = RuntimeGovernor(session=object())

    decision = governor.force_restricted("operator halt")

    assert decision == RuntimeDecision(
        mode=RuntimeMode.RESTRICTED,
        provisioning_allowed=False,
        execution_allowed=False,
        reason="operator halt",
    )
