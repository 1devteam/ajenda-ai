from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryDecision:
    retry: bool
    delay_seconds: int
    terminal: bool


class RetryPolicy:
    def __init__(self, *, max_attempts: int, base_delay_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds

    def evaluate(self, *, attempt_number: int, terminal_failure: bool) -> RetryDecision:
        if terminal_failure:
            return RetryDecision(retry=False, delay_seconds=0, terminal=True)
        if attempt_number >= self._max_attempts:
            return RetryDecision(retry=False, delay_seconds=0, terminal=True)
        delay = self._base_delay_seconds * max(1, attempt_number)
        return RetryDecision(retry=True, delay_seconds=delay, terminal=False)
