"""Fixed-window rate limiter for Ajenda AI.

This is the in-process implementation. For multi-instance production deployments,
replace with a Redis-backed sliding window implementation. The RateLimiter
interface (evaluate method signature and RateLimitDecision return type) is
stable — the middleware does not need to change when the backend is swapped.
"""

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
    """Replaceable fixed-window limiter.

    Counts requests per (tenant_id, principal_id, route) key within a fixed
    time window. When the count exceeds max_requests, returns a denial with
    a retry_after_seconds hint.

    Thread safety: NOT thread-safe. For async FastAPI use this is acceptable
    since the event loop is single-threaded. For multi-threaded WSGI use,
    wrap with a threading.Lock.
    """

    def __init__(self, *, max_requests: int, window_seconds: int) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[RateLimitKey, tuple[int, float]] = {}

    @property
    def max_requests(self) -> int:
        """The configured maximum requests per window."""
        return self._max_requests

    @property
    def window_seconds(self) -> int:
        """The configured window duration in seconds."""
        return self._window_seconds

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
