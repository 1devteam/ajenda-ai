from backend.cache.ttl_cache import TtlCache


def test_ttl_cache_set_get_invalidate() -> None:
    cache = TtlCache[int](ttl_seconds=60)
    cache.set("a", 1)
    assert cache.get("a") == 1
    cache.invalidate("a")
    assert cache.get("a") is None
