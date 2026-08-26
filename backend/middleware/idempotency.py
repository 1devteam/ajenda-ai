"""Durable HTTP idempotency middleware.

Mutating requests that opt in with ``Idempotency-Key`` must acquire one durable
PostgreSQL-backed execution owner before the application is invoked. Completed
responses are encrypted at rest and replayable across API processes. Reusing an
operation key with a changed request is a conflict rather than a second operation.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from contextlib import suppress
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from backend.services.http_idempotency_authority import (
    HttpIdempotencyAuthority,
    InMemoryHttpIdempotencyAuthority,
    ReplayResponse,
)

logger = logging.getLogger("ajenda.idempotency")

_IDEMPOTENCY_HEADER = "idempotency-key"
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH"})
_UNCACHEABLE_STATUS_CODES = frozenset({429})
_PUBLIC_SCOPE_VALUE = "public"

# Backwards-compatible explicit test authority. Production never falls back to it.
_store = InMemoryHttpIdempotencyAuthority()


def _state_value(scope: Scope, name: str) -> Any:
    state = scope.get("state")
    if isinstance(state, dict):
        return state.get(name)
    return None


def _scope_namespace(scope: Scope) -> str:
    tenant_id = _state_value(scope, "tenant_id")
    principal = _state_value(scope, "principal")
    principal_id = getattr(principal, "subject_id", None)
    if tenant_id is None or principal_id is None:
        return _PUBLIC_SCOPE_VALUE
    return f"tenant:{tenant_id}|principal:{principal_id}"


def _build_operation_key(*, scope: Scope, raw_key: str) -> str:
    method = str(scope.get("method", "")).upper()
    path = str(scope.get("path", ""))
    material = "\x00".join((_scope_namespace(scope), method, path, raw_key)).encode()
    return hashlib.sha256(material).hexdigest()


def _build_request_fingerprint(*, scope: Scope, body: bytes) -> str:
    digest = hashlib.sha256()
    query_string = scope.get("query_string", b"")
    if isinstance(query_string, str):
        query_string = query_string.encode()
    digest.update(bytes(query_string))
    digest.update(b"\x00")
    digest.update(body)
    return digest.hexdigest()


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
    return status_code < 500 and status_code not in _UNCACHEABLE_STATUS_CODES


class IdempotencyMiddleware:
    """Acquire durable ownership before executing keyed mutating requests."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        authority: HttpIdempotencyAuthority | InMemoryHttpIdempotencyAuthority | None = None,
    ) -> None:
        self._app = app
        self._injected_authority = authority
        self._runtime_authority: HttpIdempotencyAuthority | None = None

    def _resolve_authority(self, scope: Scope) -> HttpIdempotencyAuthority | InMemoryHttpIdempotencyAuthority:
        if self._injected_authority is not None:
            return self._injected_authority
        if self._runtime_authority is not None:
            return self._runtime_authority

        app = scope.get("app")
        state = getattr(app, "state", None)
        database_runtime = getattr(state, "database_runtime", None)
        settings = getattr(state, "settings", None)
        if database_runtime is None or settings is None:
            raise RuntimeError("durable idempotency authority is unavailable")
        self._runtime_authority = HttpIdempotencyAuthority(
            session_factory=database_runtime.session_factory,
            encryption_key=getattr(settings, "runtime_secret_encryption_key", None),
            previous_encryption_key=getattr(settings, "runtime_secret_encryption_key_prev", None),
        )
        return self._runtime_authority

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or str(scope.get("method", "")).upper() not in _MUTATING_METHODS:
            await self._app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw_header = headers.get(_IDEMPOTENCY_HEADER.encode())
        if raw_header is None:
            await self._app(scope, receive, send)
            return

        raw_key = raw_header.decode("utf-8", errors="replace").strip()
        if not _is_valid_uuid(raw_key):
            await self._send_json(
                scope,
                receive,
                send,
                status_code=400,
                content={"detail": "Idempotency-Key must be a valid UUID v4."},
            )
            return

        body = await _read_request_body(receive)
        receive_for_app = _replay_receive(body)
        operation_key = _build_operation_key(scope=scope, raw_key=raw_key)
        request_fingerprint = _build_request_fingerprint(scope=scope, body=body)

        try:
            authority = self._resolve_authority(scope)
            decision = await asyncio.to_thread(
                authority.claim,
                operation_key=operation_key,
                request_fingerprint=request_fingerprint,
            )
        except Exception:
            logger.exception("idempotency_claim_failed")
            await self._send_json(
                scope,
                receive_for_app,
                send,
                status_code=503,
                content={"detail": {"code": "IDEMPOTENCY_UNAVAILABLE", "message": "Idempotency authority unavailable"}},
                headers=[(b"retry-after", b"1")],
            )
            return

        if decision.status == "replay":
            assert decision.response is not None
            await self._send_replay(send, decision.response)
            return
        if decision.status == "payload_mismatch":
            await self._send_json(
                scope,
                receive_for_app,
                send,
                status_code=409,
                content={
                    "detail": {
                        "code": "IDEMPOTENCY_KEY_REUSED",
                        "message": "Idempotency-Key was already used with a different request",
                    }
                },
            )
            return
        if decision.status == "in_flight":
            await self._send_json(
                scope,
                receive_for_app,
                send,
                status_code=409,
                content={
                    "detail": {
                        "code": "IDEMPOTENCY_IN_PROGRESS",
                        "message": "An operation with this Idempotency-Key is already in progress",
                    }
                },
                headers=[(b"retry-after", b"1")],
            )
            return

        owner_token = decision.owner_token
        assert owner_token is not None
        heartbeat = asyncio.create_task(
            self._heartbeat(authority=authority, operation_key=operation_key, owner_token=owner_token)
        )
        try:
            response = await self._capture_application_response(scope, receive_for_app)
        except Exception:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await self._release_best_effort(authority, operation_key, owner_token)
            raise

        heartbeat.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat

        if _should_store_response(response.status_code):
            try:
                completed = await asyncio.to_thread(
                    authority.complete,
                    operation_key=operation_key,
                    owner_token=owner_token,
                    response=response,
                )
            except Exception:
                logger.exception("idempotency_completion_failed")
                completed = False
            if not completed:
                await self._send_json(
                    scope,
                    receive_for_app,
                    send,
                    status_code=503,
                    content={
                        "detail": {
                            "code": "IDEMPOTENCY_FINALIZATION_FAILED",
                            "message": "Operation completed but durable idempotency finalization failed",
                        }
                    },
                    headers=[(b"retry-after", b"1")],
                )
                return
        else:
            await self._release_best_effort(authority, operation_key, owner_token)

        await self._send_live(send, response)

    async def _capture_application_response(self, scope: Scope, receive: Receive) -> ReplayResponse:
        captured_status: int | None = None
        captured_headers: list[tuple[bytes, bytes]] = []
        body_parts: list[bytes] = []

        async def capture(message: Any) -> None:
            nonlocal captured_status, captured_headers
            if message["type"] == "http.response.start":
                captured_status = int(message["status"])
                captured_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body", b""))

        await self._app(scope, receive, capture)
        if captured_status is None:
            raise RuntimeError("application returned no HTTP response start")
        return ReplayResponse(
            status_code=captured_status,
            headers=captured_headers,
            body=b"".join(body_parts),
        )

    async def _heartbeat(
        self,
        *,
        authority: HttpIdempotencyAuthority | InMemoryHttpIdempotencyAuthority,
        operation_key: str,
        owner_token: str,
    ) -> None:
        while True:
            await asyncio.sleep(authority.heartbeat_interval_seconds)
            try:
                renewed = await asyncio.to_thread(
                    authority.renew,
                    operation_key=operation_key,
                    owner_token=owner_token,
                )
            except Exception:
                logger.exception("idempotency_heartbeat_failed")
                return
            if not renewed:
                logger.error("idempotency_ownership_lost")
                return

    async def _release_best_effort(
        self,
        authority: HttpIdempotencyAuthority | InMemoryHttpIdempotencyAuthority,
        operation_key: str,
        owner_token: str,
    ) -> None:
        try:
            await asyncio.to_thread(authority.release, operation_key=operation_key, owner_token=owner_token)
        except Exception:
            logger.exception("idempotency_release_failed")

    @staticmethod
    async def _send_replay(send: Send, response: ReplayResponse) -> None:
        headers = [(name, value) for name, value in response.headers if name.lower() != b"idempotency-replayed"]
        headers.append((b"idempotency-replayed", b"true"))
        await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
        await send({"type": "http.response.body", "body": response.body, "more_body": False})

    @staticmethod
    async def _send_live(send: Send, response: ReplayResponse) -> None:
        headers = [(name, value) for name, value in response.headers if name.lower() != b"idempotency-replayed"]
        headers.append((b"idempotency-replayed", b"false"))
        await send({"type": "http.response.start", "status": response.status_code, "headers": headers})
        await send({"type": "http.response.body", "body": response.body, "more_body": False})

    @staticmethod
    async def _send_json(
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        content: dict[str, Any],
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        response = JSONResponse(status_code=status_code, content=content)
        if headers:
            for name, value in headers:
                response.headers.append(name.decode("latin-1"), value.decode("latin-1"))
        await response(scope, receive, send)
