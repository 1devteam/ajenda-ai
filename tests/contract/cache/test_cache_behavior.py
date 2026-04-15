from backend.cache.ttl_cache import TtlCache


def test_cache_behavior_smoke() -> None:
    cache = TtlCache[str](ttl_seconds=60)
    cache.set("k", "v")
    assert cache.get("k") == "v"
