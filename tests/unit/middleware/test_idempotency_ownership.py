from __future__ import annotations

import asyncio

import pytest

from backend.middleware.idempotency import (
    _InProcessIdempotencyStore,
    _StoredResponse,
    build_idempotency_store,
)


def _run(awaitable):  # type: ignore[no-untyped-def]
    return asyncio.run(awaitable)


def test_claim_is_exclusive_until_owner_completes() -> None:
    store = _InProcessIdempotencyStore()
    key = "tenant-a|user-a|POST|/resources|key-a"

    first = _run(store.claim(key, owner_id="owner-a"))
    second = _run(store.claim(key, owner_id="owner-b"))

    assert first.acquired is True
    assert first.response is None
    assert second.acquired is False
    assert second.in_progress is True
    assert second.response is None

    terminal = _StoredResponse(
        status_code=201,
        headers=[(b"content-type", b"application/json")],
        body=b'{"created":true}',
    )
    assert _run(store.complete(key, owner_id="owner-b", response=terminal)) is False
    assert _run(store.complete(key, owner_id="owner-a", response=terminal)) is True

    replay = _run(store.claim(key, owner_id="owner-c"))
    assert replay.acquired is False
    assert replay.in_progress is False
    assert replay.response is not None
    assert replay.response.status_code == 201
    assert replay.response.body == b'{"created":true}'


def test_abandon_releases_only_the_current_owner_claim() -> None:
    store = _InProcessIdempotencyStore()
    key = "tenant-a|user-a|POST|/resources|key-b"

    assert _run(store.claim(key, owner_id="owner-a")).acquired is True
    _run(store.abandon(key, owner_id="owner-b"))
    assert _run(store.claim(key, owner_id="owner-c")).in_progress is True

    _run(store.abandon(key, owner_id="owner-a"))
    assert _run(store.claim(key, owner_id="owner-c")).acquired is True


def test_distributed_runtime_refuses_process_local_idempotency() -> None:
    with pytest.raises(ValueError, match="Distributed HTTP idempotency requires Redis"):
        build_idempotency_store(redis_url=None, require_distributed=True)
