"""
Redis-based rate limiting for compliance.

Provides distributed rate limiting using Redis with sliding window algorithm.
Falls back to in-memory rate limiting if Redis is unavailable.
"""

from typing import Optional, Dict
from collections import defaultdict, deque
import time


class RateLimiter:
    """
    Base rate limiter interface.
    """

    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        """
        Check if rate limit is exceeded.

        Args:
            key: Rate limit key (e.g., "agent:123:web_search")
            limit: Maximum number of requests allowed
            window_seconds: Time window in seconds

        Returns:
            Tuple of (allowed, remaining, reset_seconds)
            - allowed: Whether request is allowed
            - remaining: Number of requests remaining in window
            - reset_seconds: Seconds until window resets
        """
        raise NotImplementedError


class InMemoryRateLimiter(RateLimiter):
    """
    In-memory rate limiter using sliding window algorithm.

    Suitable for single-instance deployments or testing.
    For production multi-instance deployments, use RedisRateLimiter.
    """

    def __init__(self):
        """Initialize in-memory rate limiter"""
        # key -> deque of timestamps
        self._windows: Dict[str, deque] = defaultdict(deque)

    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        """
        Check if rate limit is exceeded using sliding window.

        Args:
            key: Rate limit key
            limit: Maximum requests allowed
            window_seconds: Time window in seconds

        Returns:
            Tuple of (allowed, remaining, reset_seconds)
        """
        now = time.time()
        window_start = now - window_seconds

        # Get or create window for this key
        window = self._windows[key]

        # Remove timestamps outside the window
        while window and window[0] < window_start:
            window.popleft()

        # Count requests in current window
        current_count = len(window)

        # Check if limit exceeded
        if current_count >= limit:
            # Calculate when oldest request will expire
            oldest_timestamp = window[0]
            reset_seconds = int(oldest_timestamp + window_seconds - now) + 1
            return False, 0, reset_seconds

        # Allow request and add timestamp
        window.append(now)
        remaining = limit - (current_count + 1)
        reset_seconds = window_seconds

        return True, remaining, reset_seconds

    def reset(self, key: str) -> None:
        """
        Reset rate limit for a key.

        Args:
            key: Rate limit key
        """
        if key in self._windows:
            del self._windows[key]

    def clear_all(self) -> None:
        """Clear all rate limits"""
        self._windows.clear()


class RedisRateLimiter(RateLimiter):
    """
    Redis-based rate limiter using sorted sets for sliding window.

    Suitable for production multi-instance deployments.
    Requires Redis server.
    """

    def __init__(self, redis_client):
        """
        Initialize Redis rate limiter.

        Args:
            redis_client: Redis client instance (redis.Redis or redis.asyncio.Redis)
        """
        self.redis = redis_client
        self._is_async = hasattr(redis_client, "zadd") and callable(
            getattr(redis_client.zadd, "__call__", None)
        )

    def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int, int]:
        """
        Check if rate limit is exceeded using Redis sorted set.

        Uses sorted set with timestamps as scores for sliding window.

        Args:
            key: Rate limit key
            limit: Maximum requests allowed
            window_seconds: Time window in seconds

        Returns:
            Tuple of (allowed, remaining, reset_seconds)
        """
        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"

        try:
            # Remove old entries outside the window
            self.redis.zremrangebyscore(redis_key, 0, window_start)

            # Count current requests in window
            current_count = self.redis.zcard(redis_key)

            # Check if limit exceeded
            if current_count >= limit:
                # Get oldest timestamp to calculate reset time
                oldest = self.redis.zrange(redis_key, 0, 0, withscores=True)
                if oldest:
                    oldest_timestamp = oldest[0][1]
                    reset_seconds = int(oldest_timestamp + window_seconds - now) + 1
                else:
                    reset_seconds = window_seconds

                return False, 0, reset_seconds

            # Add current request
            request_id = f"{now}:{id(self)}"  # Unique request ID
            self.redis.zadd(redis_key, {request_id: now})

            # Set expiration on the key
            self.redis.expire(redis_key, window_seconds + 1)

            remaining = limit - (current_count + 1)
            reset_seconds = window_seconds

            return True, remaining, reset_seconds

        except Exception as e:
            # If Redis fails, allow the request (fail open)
            # Log the error in production
            print(f"Redis rate limiter error: {e}")
            return True, limit - 1, window_seconds

    def reset(self, key: str) -> None:
        """
        Reset rate limit for a key.

        Args:
            key: Rate limit key
        """
        redis_key = f"ratelimit:{key}"
        try:
            self.redis.delete(redis_key)
        except Exception as e:
            print(f"Redis rate limiter reset error: {e}")

    def clear_all(self) -> None:
        """Clear all rate limits (use with caution!)"""
        try:
            # Find all ratelimit keys
            keys = self.redis.keys("ratelimit:*")
            if keys:
                self.redis.delete(*keys)
        except Exception as e:
            print(f"Redis rate limiter clear error: {e}")


class ComplianceRateLimiter:
    """
    Compliance-aware rate limiter.

    Integrates with policy configuration and provides
    agent/tool-specific rate limiting.
    """

    def __init__(self, limiter: Optional[RateLimiter] = None):
        """
        Initialize compliance rate limiter.

        Args:
            limiter: Rate limiter implementation (defaults to InMemoryRateLimiter)
        """
        self.limiter = limiter or InMemoryRateLimiter()

    def check_agent_tool_rate_limit(
        self,
        agent_id: str,
        agent_type: str,
        tool_name: str,
        rate_limits: Dict[str, int],
    ) -> tuple[bool, Optional[str]]:
        """
        Check rate limit for agent tool usage.

        Args:
            agent_id: Agent ID
            agent_type: Agent type
            tool_name: Tool name
            rate_limits: Rate limits dict (tool_name -> calls per minute)

        Returns:
            Tuple of (allowed, reason)
            - allowed: Whether request is allowed
            - reason: Reason for blocking (if blocked)
        """
        # Check if tool has rate limit
        if tool_name not in rate_limits:
            return True, None

        limit = rate_limits[tool_name]
        window_seconds = 60  # 1 minute window

        # Create rate limit key
        key = f"agent:{agent_id}:tool:{tool_name}"

        # Check rate limit
        allowed, remaining, reset_seconds = self.limiter.check_rate_limit(
            key=key, limit=limit, window_seconds=window_seconds
        )

        if not allowed:
            reason = (
                f"Rate limit exceeded for tool '{tool_name}'. "
                f"Limit: {limit} calls/minute. "
                f"Try again in {reset_seconds} seconds."
            )
            return False, reason

        return True, None

    def check_agent_global_rate_limit(
        self, agent_id: str, agent_type: str, global_limit: int
    ) -> tuple[bool, Optional[str]]:
        """
        Check global rate limit for agent (all tools combined).

        Args:
            agent_id: Agent ID
            agent_type: Agent type
            global_limit: Global limit (calls per minute)

        Returns:
            Tuple of (allowed, reason)
        """
        window_seconds = 60  # 1 minute window
        key = f"agent:{agent_id}:global"

        allowed, remaining, reset_seconds = self.limiter.check_rate_limit(
            key=key, limit=global_limit, window_seconds=window_seconds
        )

        if not allowed:
            reason = (
                f"Global rate limit exceeded for agent. "
                f"Limit: {global_limit} calls/minute. "
                f"Try again in {reset_seconds} seconds."
            )
            return False, reason

        return True, None

    def reset_agent_limits(self, agent_id: str, tool_name: Optional[str] = None) -> None:
        """
        Reset all rate limits for an agent.

        Args:
            agent_id: Agent ID
            tool_name: Optional tool name to reset specific tool limit
        """
        # Reset global limit
        self.limiter.reset(f"agent:{agent_id}:global")

        # Reset tool-specific limit if provided
        if tool_name:
            self.limiter.reset(f"agent:{agent_id}:tool:{tool_name}")

        # Note: To reset all tool limits without knowing tool names,
        # use Redis SCAN in production to find and delete all matching keys


# Global rate limiter instance
_global_rate_limiter: Optional[ComplianceRateLimiter] = None


def get_rate_limiter() -> ComplianceRateLimiter:
    """
    Get global rate limiter instance.

    Returns:
        ComplianceRateLimiter instance
    """
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = ComplianceRateLimiter()
    return _global_rate_limiter


def set_rate_limiter(limiter: ComplianceRateLimiter) -> None:
    """
    Set global rate limiter instance.

    Args:
        limiter: ComplianceRateLimiter instance
    """
    global _global_rate_limiter
    _global_rate_limiter = limiter


def init_redis_rate_limiter(redis_url: str) -> ComplianceRateLimiter:
    """
    Initialize Redis-based rate limiter.

    Args:
        redis_url: Redis connection URL (e.g., "redis://localhost:6379/0")

    Returns:
        ComplianceRateLimiter with Redis backend
    """
    try:
        import redis

        redis_client = redis.from_url(redis_url, decode_responses=True)
        redis_limiter = RedisRateLimiter(redis_client)
        return ComplianceRateLimiter(limiter=redis_limiter)
    except ImportError:
        print("Redis package not installed. Using in-memory rate limiter.")
        return ComplianceRateLimiter()
    except Exception as e:
        print(f"Failed to connect to Redis: {e}. Using in-memory rate limiter.")
        return ComplianceRateLimiter()
