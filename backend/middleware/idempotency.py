"""Idempotency key middleware for Ajenda AI.

Provides server-side idempotency for mutating API endpoints (POST, PUT, PATCH).
Clients send an `Idempotency-Key` header with a UUID. The server stores the
response for that key and replays it on duplicate requests within the TTL window.

Design:
- Storage backend: in-process LRU cache with TTL (suitable for single-instance
  dev/staging). For multi-instance production, swap _IdempotencyStore for a
  Redis-backed implementation — the interface is the same.
- Cache keys are scoped by tenant, principal, method, and path so one tenant or
  principal cannot replay another caller's response with the same raw key.
- Rate-limit denials are not cached so callers are re-evaluated after Retry-After
  or window reset instead of replaying a stale 429 for the idempotency TTL.
- TTL: 24 hours (86400 seconds). Duplicate requests after TTL are treated as new.
- Key format: UUID v4 string. Non-UUID keys are rejected with HTTP 400.
- Only applies to POST, PUT, PATCH methods. GET/DELETE/HEAD pass through.
- Stored response includes status code, headers, and body bytes.
- Thread-safe: uses a threading.Lock around the in-process store.

Production upgrade path:
    Replace _InProcessIdempotencyStore with a Redis implementation that uses
    SET NX EX for atomic first-write semantics and GETEX for reads. The
    IdempotencyMiddleware class does not need to change.

Usage (in main.py)::

    from backend.middleware.idempotency import IdempotencyMiddleware
    app.add_middleware(IdempotencyMiddleware)
"""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

_IDEMPOTENCY_HEADER = "idempotency-key"
_IDEMPOTENCY_TTL_SECONDS = 86_400  # 24 hours
_MAX_STORE_SIZE = 10_000  # evict oldest when exceeded
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH"})
_ANONYMOUS_SCOPE_VALUE = "anonymous"
_UNCACHEABLE_STATUS_CODES = frozenset({429})
_ONBOARDING_BODY_HASH_PREFIXES = (
    "/v1/onboarding/signup",
    "/v1/onboarding/verify-email",
    "/v1/onboarding/promote-bootstrap-key",
)


@dataclass
class _StoredResponse:
    status_code: int
    headers: list[tuple[bytes, bytes]]
    body: bytes
    stored_at: float = field(default_factory=time.monotonic)


class _InProcessIdempotencyStore:
    """Simple in-process LRU-ish store with TTL eviction.

    Not suitable for multi-instance deployments. Replace with Redis for production.
    """

    def __init__(self, ttl: float = _IDEMPOTENCY_TTL_SECONDS, max_size: int = _MAX_STORE_SIZE) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._store: dict[str, _StoredResponse] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> _StoredResponse | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() - entry.stored_at > self._ttl:
                del self._store[key]
                return None
            return entry

    def set(self, key: str, response: _StoredResponse) -> None:
        with self._lock:
            if len(self._store) >= self._max_size:
                # Evict the oldest entry
                oldest_key = next(iter(self._store))
                del self._store[oldest_key]
            self._store[key] = response


# Module-level singleton store — shared across all middleware instances
_store = _InProcessIdempotencyStore()


def _state_value(scope: Scope, name: str) -> Any:
    state = scope.get("state")
    if isinstance(state, dict):
        return state.get(name)
    return None


def _build_scoped_cache_key(*, scope: Scope, raw_key: str, body_hash: str | None = None) -> str:
    tenant_id = _state_value(scope, "tenant_id") or _ANONYMOUS_SCOPE_VALUE
    principal = _state_value(scope, "principal")
    principal_id = getattr(principal, "subject_id", None) or _ANONYMOUS_SCOPE_VALUE
    method = str(scope.get("method", "")).upper()
    path = str(scope.get("path", ""))
    parts = [str(tenant_id), str(principal_id), method, path, raw_key]
    if body_hash is not None:
        parts.append(body_hash)
    return "|".join(parts)


def _requires_body_hash(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _ONBOARDING_BODY_HASH_PREFIXES)


def _hash_request_body(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def _read_request_body(receive: Receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            continue
        chunk = message.get("body", b"")
        if chunk:
            chunks.append(chunk)
        if not message.get("more_body", False):
            break
    return b"".join(chunks)


def _replay_receive(body: bytes) -> Receive:
    sent = False

    async def replay() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    return replay


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _should_store_response(status_code: int) -> bool:
    return status_code not in _UNCACHEABLE_STATUS_CODES


class IdempotencyMiddleware:
    """Raw ASGI middleware providing idempotency for mutating endpoints.

    On first request with a given Idempotency-Key:
      1. Passes the request through to the application.
      2. Captures the response (status, headers, body).
      3. Stores it keyed by the idempotency key.
      4. Returns the response to the client with an `Idempotency-Replayed: false` header.

    On duplicate request with the same key (within TTL):
      1. Returns the stored response immediately without hitting the application.
      2. Adds `Idempotency-Replayed: true` header so clients can detect replays.

    If the Idempotency-Key header is present but not a valid UUID, returns HTTP 400.
    If the Idempotency-Key header is absent on a mutating endpoint, the request
    passes through normally (idempotency is opt-in, not required). Cached entries
    are scoped by tenant, principal, method, and path to preserve tenant isolation.
    Rate-limit denials are deliberately excluded from the cache so retries can be
    evaluated against the current limiter window.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        if method not in _MUTATING_METHODS:
            await self._app(scope, receive, send)
            return

        # Extract Idempotency-Key header (lowercase comparison per HTTP spec)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw_key = headers.get(_IDEMPOTENCY_HEADER.encode(), None)

        if raw_key is None:
            # No idempotency key — pass through
            await self._app(scope, receive, send)
            return

        raw_idempotency_key = raw_key.decode("utf-8", errors="replace").strip()

        if not _is_valid_uuid(raw_idempotency_key):
            # Malformed key — reject immediately
            error_body = b'{"detail":"Idempotency-Key must be a valid UUID v4."}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(error_body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": error_body, "more_body": False})
            return

        path = str(scope.get("path", ""))
        receive_for_app = receive
        body_hash: str | None = None
        if _requires_body_hash(path):
            body_bytes = await _read_request_body(receive)
            body_hash = _hash_request_body(body_bytes)
            receive_for_app = _replay_receive(body_bytes)
        scoped_key = _build_scoped_cache_key(scope=scope, raw_key=raw_idempotency_key, body_hash=body_hash)

        # Check store for existing response
        cached = _store.get(scoped_key)
        if cached is not None:
            # Replay the stored response
            replay_headers = [*cached.headers, (b"idempotency-replayed", b"true")]
            await send(
                {
                    "type": "http.response.start",
                    "status": cached.status_code,
                    "headers": replay_headers,
                }
            )
            await send({"type": "http.response.body", "body": cached.body, "more_body": False})
            return

        # First request — capture the response
        captured_status: int = 200
        captured_headers: list[tuple[bytes, bytes]] = []
        captured_body_parts: list[bytes] = []

        async def capturing_send(message: Any) -> None:
            nonlocal captured_status, captured_headers
            if message["type"] == "http.response.start":
                captured_status = message["status"]
                captured_headers = list(message.get("headers", []))
                # Add replay marker to live response
                outgoing_headers = [*captured_headers, (b"idempotency-replayed", b"false")]
                await send({**message, "headers": outgoing_headers})
            elif message["type"] == "http.response.body":
                body_chunk = message.get("body", b"")
                captured_body_parts.append(body_chunk)
                await send(message)
                if not message.get("more_body", False) and _should_store_response(captured_status):
                    # Response complete — store cacheable responses only.
                    _store.set(
                        scoped_key,
                        _StoredResponse(
                            status_code=captured_status,
                            headers=captured_headers,
                            body=b"".join(captured_body_parts),
                        ),
                    )
            else:
                await send(message)

        await self._app(scope, receive_for_app, capturing_send)
