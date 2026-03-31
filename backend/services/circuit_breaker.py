from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int
    failure_count: int = 0
    open: bool = False

    def record_success(self) -> None:
        self.failure_count = 0
        self.open = False

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.open = True

    def allow(self) -> bool:
        return not self.open
