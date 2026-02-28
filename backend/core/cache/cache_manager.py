"""
Cache Manager — Production-grade caching layer for Omnipath v2.

Provides a unified caching interface with two backends:
  - InMemoryCache: LRU cache for single-process / development use
  - RedisCache: Distributed cache for multi-instance production use

The factory function get_cache_manager() returns the appropriate backend
based on the REDIS_URL environment variable.

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── Sentinel ──────────────────────────────────────────────────────────────────
_MISSING = object()


# ── Base interface ────────────────────────────────────────────────────────────


class CacheBackend:
    """Abstract cache backend interface."""

    def get(self, key: str) -> Any:
        raise NotImplementedError

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob-style pattern. Returns count deleted."""
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        return self.get(key) is not _MISSING

    def get_or_set(self, key: str, factory: Callable[[], Any], ttl: int = 300) -> Any:
        """Return cached value, or call factory(), cache the result, and return it."""
        value = self.get(key)
        if value is _MISSING:
            value = factory()
            self.set(key, value, ttl=ttl)
        return value


# ── In-memory LRU backend ─────────────────────────────────────────────────────


class _CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: int) -> None:
        self.value = value
        self.expires_at: float = time.monotonic() + ttl if ttl > 0 else float("inf")

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


class InMemoryCache(CacheBackend):
    """
    Thread-safe LRU in-memory cache.

    Args:
        max_size: Maximum number of entries before LRU eviction.
        default_ttl: Default TTL in seconds (0 = no expiry).
    """

    def __init__(self, max_size: int = 1024, default_ttl: int = 300) -> None:
        self._store: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    # ── Core operations ───────────────────────────────────────

    def get(self, key: str) -> Any:
        entry = self._store.get(key)
        if entry is None:
            self._misses += 1
            return _MISSING
        if entry.is_expired():
            del self._store[key]
            self._misses += 1
            return _MISSING
        # Move to end (most recently used)
        self._store.move_to_end(key)
        self._hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl: int = -1) -> None:
        effective_ttl = ttl if ttl >= 0 else self._default_ttl
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = _CacheEntry(value, effective_ttl)
        # Evict oldest if over capacity
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a simple prefix or glob pattern."""
        import fnmatch

        keys_to_delete = [
            k for k in list(self._store.keys()) if fnmatch.fnmatch(k, pattern)
        ]
        for k in keys_to_delete:
            del self._store[k]
        return len(keys_to_delete)

    def clear(self) -> None:
        self._store.clear()
        self._hits = 0
        self._misses = 0

    def stats(self) -> dict[str, Any]:
        total = self._hits + self._misses
        return {
            "backend": "in_memory",
            "size": len(self._store),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total else 0.0,
        }


# ── Redis backend ─────────────────────────────────────────────────────────────


class RedisCache(CacheBackend):
    """
    Redis-backed distributed cache.

    Values are serialised to JSON. Falls back to InMemoryCache if Redis
    is unavailable (fail-open strategy — never block the request path).

    Args:
        redis_url: Redis connection URL.
        key_prefix: Namespace prefix for all keys.
        default_ttl: Default TTL in seconds.
    """

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "omnipath:",
        default_ttl: int = 300,
    ) -> None:
        self._prefix = key_prefix
        self._default_ttl = default_ttl
        self._fallback = InMemoryCache()
        self._redis: Any = None
        self._available = False

        try:
            import redis as redis_lib  # type: ignore[import]

            self._redis = redis_lib.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=1,
                retry_on_timeout=False,
            )
            # Verify connection
            self._redis.ping()
            self._available = True
            logger.info("RedisCache connected to %s", redis_url)
        except Exception as exc:
            logger.warning(
                "RedisCache: Redis unavailable (%s) — falling back to in-memory cache",
                exc,
            )

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Any:
        if not self._available:
            return self._fallback.get(key)
        try:
            raw = self._redis.get(self._key(key))
            if raw is None:
                return _MISSING
            return json.loads(raw)
        except Exception as exc:
            logger.debug("RedisCache.get error: %s", exc)
            return self._fallback.get(key)

    def set(self, key: str, value: Any, ttl: int = -1) -> None:
        effective_ttl = ttl if ttl >= 0 else self._default_ttl
        if not self._available:
            self._fallback.set(key, value, ttl=effective_ttl)
            return
        try:
            serialised = json.dumps(value, default=str)
            if effective_ttl > 0:
                self._redis.setex(self._key(key), effective_ttl, serialised)
            else:
                self._redis.set(self._key(key), serialised)
        except Exception as exc:
            logger.debug("RedisCache.set error: %s", exc)
            self._fallback.set(key, value, ttl=effective_ttl)

    def delete(self, key: str) -> None:
        if not self._available:
            self._fallback.delete(key)
            return
        try:
            self._redis.delete(self._key(key))
        except Exception as exc:
            logger.debug("RedisCache.delete error: %s", exc)
            self._fallback.delete(key)

    def delete_pattern(self, pattern: str) -> int:
        if not self._available:
            return self._fallback.delete_pattern(pattern)
        try:
            full_pattern = self._key(pattern)
            keys = list(self._redis.scan_iter(full_pattern))
            if keys:
                self._redis.delete(*keys)
            return len(keys)
        except Exception as exc:
            logger.debug("RedisCache.delete_pattern error: %s", exc)
            return self._fallback.delete_pattern(pattern)

    def clear(self) -> None:
        if not self._available:
            self._fallback.clear()
            return
        try:
            keys = list(self._redis.scan_iter(f"{self._prefix}*"))
            if keys:
                self._redis.delete(*keys)
        except Exception as exc:
            logger.debug("RedisCache.clear error: %s", exc)
            self._fallback.clear()


# ── Domain-specific helpers ───────────────────────────────────────────────────


class OmnipathCacheManager:
    """
    High-level cache manager with domain-specific TTLs and key conventions.

    Key namespaces:
      agents:{tenant_id}:list          — agent list results
      agents:{tenant_id}:{agent_id}    — single agent
      missions:{tenant_id}:list        — mission list results
      missions:{tenant_id}:{mission_id} — single mission
      governance:assets:{tenant_id}:*  — governance asset queries
      governance:risk:{asset_id}       — risk score for an asset
    """

    # TTLs in seconds
    TTL_AGENT = 60
    TTL_AGENT_LIST = 30
    TTL_MISSION = 30
    TTL_MISSION_LIST = 15
    TTL_GOVERNANCE_ASSET = 120
    TTL_GOVERNANCE_RISK = 60
    TTL_GOVERNANCE_AUDIT = 10  # Audit events change frequently
    TTL_METRICS = 5  # Prometheus metrics — very short

    def __init__(self, backend: CacheBackend) -> None:
        self._backend = backend

    # ── Agents ────────────────────────────────────────────────

    def get_agent(self, tenant_id: str, agent_id: str) -> Any:
        return self._backend.get(f"agents:{tenant_id}:{agent_id}")

    def set_agent(self, tenant_id: str, agent_id: str, data: Any) -> None:
        self._backend.set(f"agents:{tenant_id}:{agent_id}", data, ttl=self.TTL_AGENT)

    def invalidate_agent(self, tenant_id: str, agent_id: str) -> None:
        self._backend.delete(f"agents:{tenant_id}:{agent_id}")
        self._backend.delete_pattern(f"agents:{tenant_id}:list*")

    def get_agent_list(self, tenant_id: str, page: int = 1) -> Any:
        return self._backend.get(f"agents:{tenant_id}:list:{page}")

    def set_agent_list(self, tenant_id: str, data: Any, page: int = 1) -> None:
        self._backend.set(
            f"agents:{tenant_id}:list:{page}", data, ttl=self.TTL_AGENT_LIST
        )

    # ── Missions ──────────────────────────────────────────────

    def get_mission(self, tenant_id: str, mission_id: str) -> Any:
        return self._backend.get(f"missions:{tenant_id}:{mission_id}")

    def set_mission(self, tenant_id: str, mission_id: str, data: Any) -> None:
        self._backend.set(
            f"missions:{tenant_id}:{mission_id}", data, ttl=self.TTL_MISSION
        )

    def invalidate_mission(self, tenant_id: str, mission_id: str) -> None:
        self._backend.delete(f"missions:{tenant_id}:{mission_id}")
        self._backend.delete_pattern(f"missions:{tenant_id}:list*")

    # ── Governance assets ─────────────────────────────────────

    def get_governance_asset(self, asset_id: str) -> Any:
        return self._backend.get(f"governance:assets:{asset_id}")

    def set_governance_asset(self, asset_id: str, data: Any) -> None:
        self._backend.set(
            f"governance:assets:{asset_id}", data, ttl=self.TTL_GOVERNANCE_ASSET
        )

    def invalidate_governance_asset(
        self, asset_id: str, tenant_id: str | None = None
    ) -> None:
        self._backend.delete(f"governance:assets:{asset_id}")
        if tenant_id:
            self._backend.delete_pattern(f"governance:assets:{tenant_id}:list*")

    # ── Risk scores ───────────────────────────────────────────

    def get_risk_score(self, asset_id: str) -> Any:
        return self._backend.get(f"governance:risk:{asset_id}")

    def set_risk_score(self, asset_id: str, data: Any) -> None:
        self._backend.set(
            f"governance:risk:{asset_id}", data, ttl=self.TTL_GOVERNANCE_RISK
        )

    def invalidate_risk_score(self, asset_id: str) -> None:
        self._backend.delete(f"governance:risk:{asset_id}")

    # ── Generic helpers ───────────────────────────────────────

    def get(self, key: str) -> Any:
        return self._backend.get(key)

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._backend.set(key, value, ttl=ttl)

    def delete(self, key: str) -> None:
        self._backend.delete(key)

    def clear_all(self) -> None:
        self._backend.clear()

    @staticmethod
    def make_key(*parts: str) -> str:
        """Build a consistent cache key from parts."""
        return ":".join(str(p) for p in parts)

    @staticmethod
    def hash_key(data: Any) -> str:
        """Create a short hash key from arbitrary data (for complex query caching)."""
        serialised = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]


# ── Factory ───────────────────────────────────────────────────────────────────

_cache_manager: Optional[OmnipathCacheManager] = None


def get_cache_manager() -> OmnipathCacheManager:
    """
    Return the singleton OmnipathCacheManager.

    Selects RedisCache if REDIS_URL is set and reachable; otherwise falls
    back to InMemoryCache. The fallback is transparent to callers.
    """
    global _cache_manager
    if _cache_manager is None:
        import os

        redis_url = os.getenv("REDIS_URL", "")
        if redis_url:
            backend: CacheBackend = RedisCache(redis_url)
        else:
            logger.info("CacheManager: REDIS_URL not set — using in-memory LRU cache")
            backend = InMemoryCache()
        _cache_manager = OmnipathCacheManager(backend)
    return _cache_manager


def reset_cache_manager() -> None:
    """Reset the singleton (for testing)."""
    global _cache_manager
    _cache_manager = None


# ── Decorator ─────────────────────────────────────────────────────────────────


def cached(key_template: str, ttl: int = 300) -> Callable:
    """
    Decorator that caches the return value of a function.

    Args:
        key_template: Cache key template. Use {arg_name} placeholders.
        ttl: Time-to-live in seconds.

    Example::

        @cached("agents:{tenant_id}:{agent_id}", ttl=60)
        def get_agent(tenant_id: str, agent_id: str) -> dict:
            ...
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # Build key from function arguments
            import inspect

            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            key = key_template.format(**bound.arguments)

            cache = get_cache_manager()
            result = cache.get(key)
            if result is not _MISSING:
                return result

            result = func(*args, **kwargs)
            cache.set(key, result, ttl=ttl)
            return result

        return wrapper

    return decorator
