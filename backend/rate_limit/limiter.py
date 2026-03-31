from __future__ import annotations

from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class RateLimitKey:
    tenant_id: str
    principal_id: str
    route: str


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int | None


class RateLimiter:
    """Replaceable fixed-window limiter for production hardening."""

    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[RateLimitKey, tuple[int, float]] = {}

    def evaluate(self, key: RateLimitKey) -> RateLimitDecision:
        now = monotonic()
        count, window_start = self._buckets.get(key, (0, now))
        if now - window_start >= self._window_seconds:
            count = 0
            window_start = now
        if count >= self._max_requests:
            retry_after = max(1, int(self._window_seconds - (now - window_start)))
            return RateLimitDecision(False, 0, retry_after)
        count += 1
        self._buckets[key] = (count, window_start)
        return RateLimitDecision(True, self._max_requests - count, None)
