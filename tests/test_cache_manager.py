"""
Tests for the OmnipathCacheManager — InMemoryCache, RedisCache fallback,
OmnipathCacheManager domain helpers, and the @cached decorator.

Built with Pride for Obex Blackvault
"""

import pytest
import time

from backend.core.cache.cache_manager import (
    InMemoryCache,
    OmnipathCacheManager,
    RedisCache,
    get_cache_manager,
    reset_cache_manager,
    cached,
    _MISSING,
)

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure the cache singleton is reset between tests."""
    reset_cache_manager()
    yield
    reset_cache_manager()


@pytest.fixture
def mem_cache():
    return InMemoryCache(max_size=10, default_ttl=60)


@pytest.fixture
def manager(mem_cache):
    return OmnipathCacheManager(mem_cache)


# ── InMemoryCache ─────────────────────────────────────────────────────────────


class TestInMemoryCache:

    def test_set_and_get(self, mem_cache):
        mem_cache.set("key1", "value1")
        assert mem_cache.get("key1") == "value1"

    def test_missing_key_returns_sentinel(self, mem_cache):
        assert mem_cache.get("nonexistent") is _MISSING

    def test_ttl_expiry(self, mem_cache):
        mem_cache.set("expiring", "soon", ttl=1)
        assert mem_cache.get("expiring") == "soon"
        time.sleep(1.1)
        assert mem_cache.get("expiring") is _MISSING

    def test_no_expiry_when_ttl_zero(self, mem_cache):
        mem_cache.set("permanent", "value", ttl=0)
        time.sleep(0.05)
        assert mem_cache.get("permanent") == "value"

    def test_lru_eviction(self):
        cache = InMemoryCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # Access 'a' to make it recently used
        cache.get("a")
        # Adding 'd' should evict 'b' (least recently used)
        cache.set("d", 4)
        assert cache.get("b") is _MISSING
        assert cache.get("a") == 1
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_delete(self, mem_cache):
        mem_cache.set("to_delete", "value")
        mem_cache.delete("to_delete")
        assert mem_cache.get("to_delete") is _MISSING

    def test_delete_nonexistent_is_safe(self, mem_cache):
        mem_cache.delete("ghost")  # Should not raise

    def test_delete_pattern(self, mem_cache):
        mem_cache.set("agents:t1:list", [1, 2])
        mem_cache.set("agents:t1:list:2", [3, 4])
        mem_cache.set("agents:t1:agent-001", {"id": "agent-001"})
        deleted = mem_cache.delete_pattern("agents:t1:list*")
        assert deleted == 2
        assert mem_cache.get("agents:t1:agent-001") == {"id": "agent-001"}

    def test_clear(self, mem_cache):
        mem_cache.set("a", 1)
        mem_cache.set("b", 2)
        mem_cache.clear()
        assert mem_cache.get("a") is _MISSING
        assert mem_cache.get("b") is _MISSING

    def test_get_or_set(self, mem_cache):
        call_count = {"n": 0}

        def factory():
            call_count["n"] += 1
            return "computed"

        result1 = mem_cache.get_or_set("computed_key", factory)
        result2 = mem_cache.get_or_set("computed_key", factory)
        assert result1 == "computed"
        assert result2 == "computed"
        assert call_count["n"] == 1  # Factory called only once

    def test_stats(self, mem_cache):
        mem_cache.set("x", 1)
        mem_cache.get("x")  # hit
        mem_cache.get("missing")  # miss
        stats = mem_cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["backend"] == "in_memory"

    def test_overwrite_existing_key(self, mem_cache):
        mem_cache.set("key", "old")
        mem_cache.set("key", "new")
        assert mem_cache.get("key") == "new"

    def test_stores_complex_types(self, mem_cache):
        data = {"nested": {"list": [1, 2, 3], "bool": True}}
        mem_cache.set("complex", data)
        assert mem_cache.get("complex") == data


# ── RedisCache fallback ───────────────────────────────────────────────────────


class TestRedisCacheFallback:
    """
    Tests that RedisCache gracefully falls back to InMemoryCache
    when Redis is not available.
    """

    def test_falls_back_on_unavailable_redis(self):
        cache = RedisCache("redis://localhost:19999")  # Nothing listening
        assert cache._available is False

    def test_get_uses_fallback(self):
        cache = RedisCache("redis://localhost:19999")
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_delete_uses_fallback(self):
        cache = RedisCache("redis://localhost:19999")
        cache.set("k", "v")
        cache.delete("k")
        assert cache.get("k") is _MISSING

    def test_delete_pattern_uses_fallback(self):
        cache = RedisCache("redis://localhost:19999")
        cache.set("ns:a", 1)
        cache.set("ns:b", 2)
        cache.set("other:c", 3)
        deleted = cache.delete_pattern("ns:*")
        assert deleted == 2
        assert cache.get("other:c") == 3


# ── OmnipathCacheManager ──────────────────────────────────────────────────────


class TestOmnipathCacheManager:

    def test_agent_set_and_get(self, manager):
        manager.set_agent("t1", "agent-001", {"name": "Alpha"})
        result = manager.get_agent("t1", "agent-001")
        assert result == {"name": "Alpha"}

    def test_agent_miss(self, manager):
        assert manager.get_agent("t1", "ghost") is _MISSING

    def test_invalidate_agent_clears_agent_and_list(self, manager):
        manager.set_agent("t1", "agent-001", {"name": "Alpha"})
        manager._backend.set("agents:t1:list:1", [{"id": "agent-001"}])
        manager.invalidate_agent("t1", "agent-001")
        assert manager.get_agent("t1", "agent-001") is _MISSING
        assert manager._backend.get("agents:t1:list:1") is _MISSING

    def test_mission_set_and_get(self, manager):
        manager.set_mission("t1", "mission-001", {"status": "running"})
        assert manager.get_mission("t1", "mission-001") == {"status": "running"}

    def test_invalidate_mission(self, manager):
        manager.set_mission("t1", "mission-001", {"status": "running"})
        manager._backend.set("missions:t1:list:1", [{"id": "mission-001"}])
        manager.invalidate_mission("t1", "mission-001")
        assert manager.get_mission("t1", "mission-001") is _MISSING
        assert manager._backend.get("missions:t1:list:1") is _MISSING

    def test_governance_asset_set_and_get(self, manager):
        manager.set_governance_asset("asset-001", {"risk_tier": "HIGH"})
        assert manager.get_governance_asset("asset-001") == {"risk_tier": "HIGH"}

    def test_invalidate_governance_asset(self, manager):
        manager.set_governance_asset("asset-001", {"risk_tier": "HIGH"})
        manager.invalidate_governance_asset("asset-001")
        assert manager.get_governance_asset("asset-001") is _MISSING

    def test_risk_score_set_and_get(self, manager):
        manager.set_risk_score("asset-001", {"score": 75.0, "tier": "HIGH"})
        assert manager.get_risk_score("asset-001") == {"score": 75.0, "tier": "HIGH"}

    def test_invalidate_risk_score(self, manager):
        manager.set_risk_score("asset-001", {"score": 75.0})
        manager.invalidate_risk_score("asset-001")
        assert manager.get_risk_score("asset-001") is _MISSING

    def test_generic_get_set_delete(self, manager):
        manager.set("custom:key", 42, ttl=60)
        assert manager.get("custom:key") == 42
        manager.delete("custom:key")
        assert manager.get("custom:key") is _MISSING

    def test_clear_all(self, manager):
        manager.set_agent("t1", "a1", {})
        manager.set_mission("t1", "m1", {})
        manager.clear_all()
        assert manager.get_agent("t1", "a1") is _MISSING
        assert manager.get_mission("t1", "m1") is _MISSING

    def test_make_key(self):
        key = OmnipathCacheManager.make_key("agents", "t1", "agent-001")
        assert key == "agents:t1:agent-001"

    def test_hash_key_is_deterministic(self):
        data = {"query": "list_agents", "page": 1, "tenant": "t1"}
        k1 = OmnipathCacheManager.hash_key(data)
        k2 = OmnipathCacheManager.hash_key(data)
        assert k1 == k2
        assert len(k1) == 16

    def test_hash_key_differs_for_different_data(self):
        k1 = OmnipathCacheManager.hash_key({"page": 1})
        k2 = OmnipathCacheManager.hash_key({"page": 2})
        assert k1 != k2


# ── get_cache_manager factory ─────────────────────────────────────────────────


class TestGetCacheManager:

    def test_returns_omnipath_manager(self):
        manager = get_cache_manager()
        assert isinstance(manager, OmnipathCacheManager)

    def test_singleton(self):
        m1 = get_cache_manager()
        m2 = get_cache_manager()
        assert m1 is m2

    def test_reset_creates_new_instance(self):
        m1 = get_cache_manager()
        reset_cache_manager()
        m2 = get_cache_manager()
        assert m1 is not m2

    def test_uses_in_memory_when_no_redis_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        manager = get_cache_manager()
        assert isinstance(manager._backend, InMemoryCache)


# ── @cached decorator ─────────────────────────────────────────────────────────


class TestCachedDecorator:

    def test_caches_return_value(self):
        call_count = {"n": 0}

        @cached("test:decorated:{x}", ttl=60)
        def compute(x: int) -> int:
            call_count["n"] += 1
            return x * 2

        assert compute(5) == 10
        assert compute(5) == 10
        assert call_count["n"] == 1  # Only called once

    def test_different_args_are_cached_separately(self):
        call_count = {"n": 0}

        @cached("test:multi:{x}", ttl=60)
        def compute(x: int) -> int:
            call_count["n"] += 1
            return x * 3

        assert compute(2) == 6
        assert compute(3) == 9
        assert call_count["n"] == 2

    def test_caches_none_return(self):
        call_count = {"n": 0}

        @cached("test:none:{x}", ttl=60)
        def returns_none(x: int):
            call_count["n"] += 1
            return None

        result1 = returns_none(1)
        result2 = returns_none(1)
        assert result1 is None
        assert result2 is None
        assert call_count["n"] == 1
