"""Fixed-window rate limiter for Ajenda AI.

This is the in-process implementation. For multi-instance production deployments,
replace with a Redis-backed sliding window implementation. The RateLimiter
interface (evaluate method signature and RateLimitDecision return type) is
stable — the middleware does not need to change when the backend is swapped.

Per-route policy overrides
--------------------------
High-risk routes (e.g. webhook registration, admin tenant provisioning) need
tighter limits than the global default. Pass a ``route_policies`` mapping to
``RateLimiter.__init__`` to override the global ``max_requests`` / ``window_seconds``
for specific route prefixes.

Example::

    from backend.rate_limit.limiter import RateLimiter, RoutePolicy

    limiter = RateLimiter(
        max_requests=100,
        window_seconds=60,
        route_policies={
            "/v1/webhooks": RoutePolicy(max_requests=10, window_seconds=60),
            "/v1/admin":    RoutePolicy(max_requests=20, window_seconds=60),
        },
    )

Route matching uses a *longest-prefix* strategy: the most specific matching
prefix wins. If no prefix matches, the global defaults apply.
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


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    """Per-route rate limit override.

    Args:
        max_requests: Maximum number of requests allowed within ``window_seconds``.
        window_seconds: Duration of the fixed window in seconds.
    """

    max_requests: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.max_requests <= 0:
            raise ValueError("RoutePolicy.max_requests must be positive")
        if self.window_seconds <= 0:
            raise ValueError("RoutePolicy.window_seconds must be positive")


class RateLimiter:
    """Replaceable fixed-window limiter with optional per-route policy overrides.

    Counts requests per (tenant_id, principal_id, route) key within a fixed
    time window. When the count exceeds max_requests, returns a denial with
    a retry_after_seconds hint.

    Per-route overrides are matched by longest prefix. For example, if
    route_policies contains ``"/v1/webhooks"`` and the request path is
    ``"/v1/webhooks/abc-123"``, the override applies.

    Thread safety: NOT thread-safe. For async FastAPI use this is acceptable
    since the event loop is single-threaded. For multi-threaded WSGI use,
    wrap with a threading.Lock.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        route_policies: dict[str, RoutePolicy] | None = None,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        # Sort by descending prefix length so longest match wins
        self._route_policies: list[tuple[str, RoutePolicy]] = sorted(
            (route_policies or {}).items(),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        self._buckets: dict[tuple[RateLimitKey, int, int], tuple[int, float]] = {}

    @property
    def max_requests(self) -> int:
        """The configured global maximum requests per window."""
        return self._max_requests

    @property
    def window_seconds(self) -> int:
        """The configured global window duration in seconds."""
        return self._window_seconds

    @property
    def route_policies(self) -> dict[str, RoutePolicy]:
        """A copy of the per-route policy map (prefix → RoutePolicy)."""
        return dict(self._route_policies)

    def _resolve_policy(self, route: str) -> tuple[int, int]:
        """Return (max_requests, window_seconds) for the given route.

        Applies the longest-prefix match from route_policies. Falls back to
        the global defaults if no prefix matches.
        """
        for prefix, policy in self._route_policies:
            if route == prefix or route.startswith(prefix + "/") or route.startswith(prefix):
                return policy.max_requests, policy.window_seconds
        return self._max_requests, self._window_seconds

    def evaluate(self, key: RateLimitKey) -> RateLimitDecision:
        max_req, window_sec = self._resolve_policy(key.route)
        return self.evaluate_with_policy(
            key,
            max_requests=max_req,
            window_seconds=window_sec,
        )

    def evaluate_with_policy(
        self,
        key: RateLimitKey,
        *,
        max_requests: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        """Evaluate a request against explicit limits."""
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        # Bucket key includes the effective limits so that policy changes
        # don't bleed across old and new buckets.
        bucket_key = (key, max_requests, window_seconds)
        now = monotonic()
        count, window_start = self._buckets.get(bucket_key, (0, now))
        if now - window_start >= window_seconds:
            count = 0
            window_start = now
        if count >= max_requests:
            retry_after = max(1, int(window_seconds - (now - window_start)))
            return RateLimitDecision(False, 0, retry_after)
        count += 1
        self._buckets[bucket_key] = (count, window_start)
        return RateLimitDecision(True, max_requests - count, None)
