"""Idempotency key middleware for Ajenda AI.

Provides server-side idempotency for mutating API endpoints (POST, PUT, PATCH).
Clients send an ``Idempotency-Key`` header with a UUID. A request must acquire
exclusive ownership of its scoped key before application code executes. Once the
response is complete, the owner atomically replaces the claim with the terminal
response so retries can replay without re-executing the mutation.

Production uses Redis-backed ownership so multiple Uvicorn workers share one
idempotency authority. Development/test may use the in-process implementation
when only one API worker is active.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import anyio
import redis
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_IDEMPOTENCY_HEADER = "idempotency-key"
_IDEMPOTENCY_TTL_SECONDS = 86_400  # 24 hours
_IDEMPOTENCY_CLAIM_TTL_SECONDS = 1_800  # abandoned in-flight claims recover after 30 minutes
_MAX_STORE_SIZE = 10_000  # evict oldest when exceeded in development/test
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH"})
_ANONYMOUS_SCOPE_VALUE = "anonymous"
_UNCACHEABLE_STATUS_CODES = frozenset({429})
_ONBOARDING_BODY_HASH_PREFIXES = (
    "/v1/onboarding/signup",
    "/v1/onboarding/verify-email",
    "/v1/onboarding/promote-bootstrap-key",
)
_REDIS_KEY_PREFIX = "ajenda:idempotency:v1:"
_REDIS_PENDING_PREFIX = b"pending:"
_REDIS_COMPLETE_PREFIX = b"complete:"


@dataclass
class _StoredResponse:
    status_code: int
    headers: list[tuple[bytes, bytes]]
    body: bytes
    stored_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class _PendingClaim:
    owner_id: str
    claimed_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True)
class _ClaimResult:
    acquired: bool
    response: _StoredResponse | None = None
    in_progress: bool = False


class _IdempotencyStore:
    async def claim(self, key: str, *, owner_id: str) -> _ClaimResult:
        raise NotImplementedError

    async def complete(self, key: str, *, owner_id: str, response: _StoredResponse) -> bool:
        raise NotImplementedError

    async def abandon(self, key: str, *, owner_id: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


class _InProcessIdempotencyStore(_IdempotencyStore):
    """Single-process claim/terminal store for development and unit tests."""

    def __init__(
        self,
        ttl: float = _IDEMPOTENCY_TTL_SECONDS,
        claim_ttl: float = _IDEMPOTENCY_CLAIM_TTL_SECONDS,
        max_size: int = _MAX_STORE_SIZE,
    ) -> None:
        self._ttl = ttl
        self._claim_ttl = claim_ttl
        self._max_size = max_size
        self._store: dict[str, _StoredResponse | _PendingClaim] = {}
        self._lock = threading.Lock()

    def _expired(self, entry: _StoredResponse | _PendingClaim) -> bool:
        now = time.monotonic()
        if isinstance(entry, _StoredResponse):
            return now - entry.stored_at > self._ttl
        return now - entry.claimed_at > self._claim_ttl

    async def claim(self, key: str, *, owner_id: str) -> _ClaimResult:
        with self._lock:
            entry = self._store.get(key)
            if entry is not None and self._expired(entry):
                del self._store[key]
                entry = None
            if entry is None:
                if len(self._store) >= self._max_size:
                    oldest_key = next(iter(self._store))
                    del self._store[oldest_key]
                self._store[key] = _PendingClaim(owner_id=owner_id)
                return _ClaimResult(acquired=True)
            if isinstance(entry, _StoredResponse):
                return _ClaimResult(acquired=False, response=entry)
            return _ClaimResult(acquired=False, in_progress=True)

    async def complete(self, key: str, *, owner_id: str, response: _StoredResponse) -> bool:
        with self._lock:
            entry = self._store.get(key)
            if not isinstance(entry, _PendingClaim) or entry.owner_id != owner_id:
                return False
            self._store[key] = response
            return True

    async def abandon(self, key: str, *, owner_id: str) -> None:
        with self._lock:
            entry = self._store.get(key)
            if isinstance(entry, _PendingClaim) and entry.owner_id == owner_id:
                del self._store[key]


class _RedisIdempotencyStore(_IdempotencyStore):
    """Redis-backed distributed ownership and terminal-response store."""

    _COMPLETE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""
    _ABANDON_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if current ~= ARGV[1] then
    return 0
end
return redis.call('DEL', KEYS[1])
"""

    def __init__(
        self,
        redis_url: str,
        *,
        ttl_seconds: int = _IDEMPOTENCY_TTL_SECONDS,
        claim_ttl_seconds: int = _IDEMPOTENCY_CLAIM_TTL_SECONDS,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._claim_ttl_seconds = claim_ttl_seconds
        self._client: Any = redis.Redis.from_url(redis_url, decode_responses=False)

    @staticmethod
    def _redis_key(key: str) -> str:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return f"{_REDIS_KEY_PREFIX}{digest}"

    @staticmethod
    def _pending_value(owner_id: str) -> bytes:
        return _REDIS_PENDING_PREFIX + owner_id.encode("utf-8")

    @staticmethod
    def _encode_response(response: _StoredResponse) -> bytes:
        payload = {
            "status_code": response.status_code,
            "headers": [
                [base64.b64encode(name).decode("ascii"), base64.b64encode(value).decode("ascii")]
                for name, value in response.headers
            ],
            "body": base64.b64encode(response.body).decode("ascii"),
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return _REDIS_COMPLETE_PREFIX + encoded

    @staticmethod
    def _decode_response(raw: bytes) -> _StoredResponse:
        payload = json.loads(raw[len(_REDIS_COMPLETE_PREFIX) :].decode("utf-8"))
        headers = [(base64.b64decode(str(name)), base64.b64decode(str(value))) for name, value in payload["headers"]]
        return _StoredResponse(
            status_code=int(payload["status_code"]),
            headers=headers,
            body=base64.b64decode(str(payload["body"])),
        )

    async def claim(self, key: str, *, owner_id: str) -> _ClaimResult:
        redis_key = self._redis_key(key)
        pending_value = self._pending_value(owner_id)

        def _claim() -> _ClaimResult:
            acquired = self._client.set(
                redis_key,
                pending_value,
                nx=True,
                ex=self._claim_ttl_seconds,
            )
            if acquired:
                return _ClaimResult(acquired=True)
            current = self._client.get(redis_key)
            if current is None:
                acquired_after_expiry = self._client.set(
                    redis_key,
                    pending_value,
                    nx=True,
                    ex=self._claim_ttl_seconds,
                )
                return _ClaimResult(acquired=bool(acquired_after_expiry), in_progress=not bool(acquired_after_expiry))
            if not isinstance(current, bytes):
                return _ClaimResult(acquired=False, in_progress=True)
            if current.startswith(_REDIS_COMPLETE_PREFIX):
                return _ClaimResult(acquired=False, response=self._decode_response(current))
            return _ClaimResult(acquired=False, in_progress=True)

        return await anyio.to_thread.run_sync(_claim)

    async def complete(self, key: str, *, owner_id: str, response: _StoredResponse) -> bool:
        redis_key = self._redis_key(key)
        pending_value = self._pending_value(owner_id)
        complete_value = self._encode_response(response)

        def _complete() -> bool:
            result = self._client.eval(
                self._COMPLETE_SCRIPT,
                1,
                redis_key,
                pending_value,
                complete_value,
                str(self._ttl_seconds),
            )
            return result == 1

        return await anyio.to_thread.run_sync(_complete)

    async def abandon(self, key: str, *, owner_id: str) -> None:
        redis_key = self._redis_key(key)
        pending_value = self._pending_value(owner_id)

        def _abandon() -> None:
            self._client.eval(self._ABANDON_SCRIPT, 1, redis_key, pending_value)

        await anyio.to_thread.run_sync(_abandon)

    def close(self) -> None:
        self._client.close()


# Default single-process store for direct middleware construction in unit tests.
_store = _InProcessIdempotencyStore()


def build_idempotency_store(*, redis_url: str | None, require_distributed: bool) -> _IdempotencyStore:
    if redis_url is not None and redis_url.strip():
        return _RedisIdempotencyStore(redis_url.strip())
    if require_distributed:
        raise ValueError("Distributed HTTP idempotency requires Redis-backed AJENDA_QUEUE_URL")
    return _store


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

    async def replay() -> Message:
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


async def _send_stored_response(send: Send, response: _StoredResponse, *, replayed: bool) -> None:
    marker = b"true" if replayed else b"false"
    headers = [*response.headers, (b"idempotency-replayed", marker)]
    await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": response.body, "more_body": False})


async def _send_in_progress_response(send: Send) -> None:
    body = b'{"detail":"Request with this Idempotency-Key is already in progress."}'
    await send(
        {
            "type": "http.response.start",
            "status": 409,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", b"1"),
                (b"idempotency-replayed", b"false"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


class IdempotencyMiddleware:
    """Raw ASGI middleware providing scoped claim-before-execute idempotency."""

    def __init__(self, app: ASGIApp, *, store: _IdempotencyStore | None = None) -> None:
        self._app = app
        self._store = store or _store

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        method = scope.get("method", "").upper()
        if method not in _MUTATING_METHODS:
            await self._app(scope, receive, send)
            return

        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        raw_key = headers.get(_IDEMPOTENCY_HEADER.encode())
        if raw_key is None:
            await self._app(scope, receive, send)
            return

        raw_idempotency_key = raw_key.decode("utf-8", errors="replace").strip()
        if not _is_valid_uuid(raw_idempotency_key):
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
        owner_id = str(uuid.uuid4())
        claim = await self._store.claim(scoped_key, owner_id=owner_id)

        if claim.response is not None:
            await _send_stored_response(send, claim.response, replayed=True)
            return
        if not claim.acquired:
            await _send_in_progress_response(send)
            return

        captured_status = 200
        captured_headers: list[tuple[bytes, bytes]] = []
        captured_body_parts: list[bytes] = []
        response_started = False
        response_complete = False

        async def capture_send(message: Message) -> None:
            nonlocal captured_status, captured_headers, response_started, response_complete
            if message["type"] == "http.response.start":
                captured_status = int(message["status"])
                captured_headers = list(message.get("headers", []))
                response_started = True
                return
            if message["type"] == "http.response.body":
                captured_body_parts.append(message.get("body", b""))
                if not message.get("more_body", False):
                    response_complete = True

        try:
            await self._app(scope, receive_for_app, capture_send)
        except Exception:
            await self._store.abandon(scoped_key, owner_id=owner_id)
            raise

        if not response_started or not response_complete:
            await self._store.abandon(scoped_key, owner_id=owner_id)
            raise RuntimeError("IdempotencyMiddleware captured an incomplete HTTP response")

        response = _StoredResponse(
            status_code=captured_status,
            headers=captured_headers,
            body=b"".join(captured_body_parts),
        )
        if _should_store_response(captured_status):
            completed = await self._store.complete(scoped_key, owner_id=owner_id, response=response)
            if not completed:
                raise RuntimeError("Idempotency ownership was lost before terminal response persistence")
        else:
            await self._store.abandon(scoped_key, owner_id=owner_id)

        await _send_stored_response(send, response, replayed=False)
