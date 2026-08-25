from __future__ import annotations

import asyncio

from backend.middleware.idempotency import _RedisIdempotencyStore, _StoredResponse


def _run(awaitable):  # type: ignore[no-untyped-def]
    return asyncio.run(awaitable)


def test_redis_claim_is_shared_across_independent_store_instances(redis_url: str, redis_client) -> None:  # type: ignore[no-untyped-def]
    store_a = _RedisIdempotencyStore(redis_url)
    store_b = _RedisIdempotencyStore(redis_url)
    key = "tenant-a|user-a|POST|/resources|distributed-key"

    try:
        first = _run(store_a.claim(key, owner_id="worker-a"))
        second = _run(store_b.claim(key, owner_id="worker-b"))

        assert first.acquired is True
        assert second.acquired is False
        assert second.in_progress is True
        assert second.response is None

        response = _StoredResponse(
            status_code=201,
            headers=[(b"content-type", b"application/json")],
            body=b'{"created":true,"worker":"a"}',
        )
        assert _run(store_b.complete(key, owner_id="worker-b", response=response)) is False
        assert _run(store_a.complete(key, owner_id="worker-a", response=response)) is True

        replay = _run(store_b.claim(key, owner_id="worker-b"))
        assert replay.acquired is False
        assert replay.in_progress is False
        assert replay.response is not None
        assert replay.response.status_code == 201
        assert replay.response.headers == [(b"content-type", b"application/json")]
        assert replay.response.body == b'{"created":true,"worker":"a"}'
    finally:
        store_a.close()
        store_b.close()


def test_redis_abandoned_claim_can_be_reacquired_by_another_instance(redis_url: str, redis_client) -> None:  # type: ignore[no-untyped-def]
    store_a = _RedisIdempotencyStore(redis_url)
    store_b = _RedisIdempotencyStore(redis_url)
    key = "tenant-a|user-a|POST|/resources|abandoned-key"

    try:
        assert _run(store_a.claim(key, owner_id="worker-a")).acquired is True
        assert _run(store_b.claim(key, owner_id="worker-b")).in_progress is True

        _run(store_a.abandon(key, owner_id="worker-a"))
        assert _run(store_b.claim(key, owner_id="worker-b")).acquired is True
    finally:
        store_a.close()
        store_b.close()
