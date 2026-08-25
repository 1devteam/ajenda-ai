"""Durable authority for HTTP idempotency claims and replay receipts."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from typing import Callable, Literal

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy.orm import Session

from backend.domain.http_idempotency import HTTP_IDEMPOTENCY_STATUS_CLAIMING, HTTP_IDEMPOTENCY_STATUS_COMPLETED
from backend.repositories.http_idempotency_repository import HttpIdempotencyRepository

_DEFAULT_RECEIPT_TTL_SECONDS = 86_400
_DEFAULT_CLAIM_TTL_SECONDS = 120
_TEST_KEY = base64.urlsafe_b64encode(b"\x01" * 32)

DecisionStatus = Literal["owner", "replay", "in_flight", "payload_mismatch"]


@dataclass(frozen=True)
class ReplayResponse:
    status_code: int
    headers: list[tuple[bytes, bytes]]
    body: bytes


@dataclass(frozen=True)
class IdempotencyDecision:
    status: DecisionStatus
    owner_token: str | None = None
    response: ReplayResponse | None = None


class HttpIdempotencyAuthority:
    """Coordinates one durable execution owner across API processes."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        encryption_key: str | bytes | None,
        previous_encryption_key: str | bytes | None = None,
        claim_ttl_seconds: int = _DEFAULT_CLAIM_TTL_SECONDS,
        receipt_ttl_seconds: int = _DEFAULT_RECEIPT_TTL_SECONDS,
    ) -> None:
        if claim_ttl_seconds <= 0:
            raise ValueError("claim_ttl_seconds must be positive")
        if receipt_ttl_seconds <= 0:
            raise ValueError("receipt_ttl_seconds must be positive")
        key = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
        previous_key = (
            previous_encryption_key.encode()
            if isinstance(previous_encryption_key, str)
            else previous_encryption_key
        )
        fernets = [Fernet(key or _TEST_KEY)]
        if previous_key is not None:
            fernets.append(Fernet(previous_key))
        self._fernet = MultiFernet(fernets)
        self._session_factory = session_factory
        self._claim_ttl_seconds = claim_ttl_seconds
        self._receipt_ttl_seconds = receipt_ttl_seconds

    @property
    def heartbeat_interval_seconds(self) -> float:
        return max(1.0, self._claim_ttl_seconds / 3)

    def claim(self, *, operation_key: str, request_fingerprint: str) -> IdempotencyDecision:
        owner_token = str(uuid.uuid4())
        session = self._session_factory()
        try:
            repo = HttpIdempotencyRepository(session)
            result = repo.claim(
                operation_key=operation_key,
                request_fingerprint=request_fingerprint,
                owner_token=owner_token,
                now=repo.utcnow(),
                claim_ttl_seconds=self._claim_ttl_seconds,
                receipt_ttl_seconds=self._receipt_ttl_seconds,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        if result.status == "acquired":
            return IdempotencyDecision(status="owner", owner_token=owner_token)
        if result.status == "replay" and result.response_ciphertext:
            return IdempotencyDecision(status="replay", response=self._decrypt_response(result.response_ciphertext))
        if result.status == "payload_mismatch":
            return IdempotencyDecision(status="payload_mismatch")
        return IdempotencyDecision(status="in_flight")

    def renew(self, *, operation_key: str, owner_token: str) -> bool:
        session = self._session_factory()
        try:
            repo = HttpIdempotencyRepository(session)
            renewed = repo.renew(
                operation_key=operation_key,
                owner_token=owner_token,
                now=repo.utcnow(),
                claim_ttl_seconds=self._claim_ttl_seconds,
            )
            session.commit()
            return renewed
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def complete(
        self,
        *,
        operation_key: str,
        owner_token: str,
        response: ReplayResponse,
    ) -> bool:
        ciphertext = self._encrypt_response(response)
        session = self._session_factory()
        try:
            repo = HttpIdempotencyRepository(session)
            completed = repo.complete(
                operation_key=operation_key,
                owner_token=owner_token,
                response_ciphertext=ciphertext,
                now=repo.utcnow(),
                receipt_ttl_seconds=self._receipt_ttl_seconds,
            )
            session.commit()
            return completed
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def release(self, *, operation_key: str, owner_token: str) -> bool:
        session = self._session_factory()
        try:
            released = HttpIdempotencyRepository(session).release(
                operation_key=operation_key,
                owner_token=owner_token,
            )
            session.commit()
            return released
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _encrypt_response(self, response: ReplayResponse) -> str:
        payload = {
            "status_code": response.status_code,
            "headers": [
                [base64.b64encode(name).decode("ascii"), base64.b64encode(value).decode("ascii")]
                for name, value in response.headers
            ],
            "body": base64.b64encode(response.body).decode("ascii"),
        }
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return self._fernet.encrypt(serialized).decode()

    def _decrypt_response(self, ciphertext: str) -> ReplayResponse:
        try:
            payload = json.loads(self._fernet.decrypt(ciphertext.encode()).decode())
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid durable HTTP idempotency response ciphertext") from exc
        headers = [
            (base64.b64decode(str(name)), base64.b64decode(str(value)))
            for name, value in payload["headers"]
        ]
        return ReplayResponse(
            status_code=int(payload["status_code"]),
            headers=headers,
            body=base64.b64decode(str(payload["body"])),
        )


@dataclass
class _InMemoryReceipt:
    request_fingerprint: str
    owner_token: str
    status: str
    claim_expires_at: float
    expires_at: float
    response: ReplayResponse | None = None


class InMemoryHttpIdempotencyAuthority:
    """Process-local authority used only when explicitly injected by unit tests."""

    def __init__(
        self,
        *,
        claim_ttl_seconds: int = _DEFAULT_CLAIM_TTL_SECONDS,
        receipt_ttl_seconds: int = _DEFAULT_RECEIPT_TTL_SECONDS,
    ) -> None:
        import threading
        import time

        self._claim_ttl_seconds = claim_ttl_seconds
        self._receipt_ttl_seconds = receipt_ttl_seconds
        self._lock = threading.Lock()
        self._clock = time.monotonic
        self._store: dict[str, _InMemoryReceipt] = {}

    @property
    def heartbeat_interval_seconds(self) -> float:
        return max(1.0, self._claim_ttl_seconds / 3)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def claim(self, *, operation_key: str, request_fingerprint: str) -> IdempotencyDecision:
        owner_token = str(uuid.uuid4())
        now = self._clock()
        with self._lock:
            row = self._store.get(operation_key)
            if row is None or row.expires_at <= now:
                self._store[operation_key] = _InMemoryReceipt(
                    request_fingerprint=request_fingerprint,
                    owner_token=owner_token,
                    status=HTTP_IDEMPOTENCY_STATUS_CLAIMING,
                    claim_expires_at=now + self._claim_ttl_seconds,
                    expires_at=now + self._receipt_ttl_seconds,
                )
                return IdempotencyDecision(status="owner", owner_token=owner_token)
            if row.request_fingerprint != request_fingerprint:
                return IdempotencyDecision(status="payload_mismatch")
            if row.status == HTTP_IDEMPOTENCY_STATUS_COMPLETED and row.response is not None:
                return IdempotencyDecision(status="replay", response=row.response)
            if row.claim_expires_at <= now:
                row.owner_token = owner_token
                row.claim_expires_at = now + self._claim_ttl_seconds
                row.expires_at = now + self._receipt_ttl_seconds
                return IdempotencyDecision(status="owner", owner_token=owner_token)
            return IdempotencyDecision(status="in_flight")

    def renew(self, *, operation_key: str, owner_token: str) -> bool:
        now = self._clock()
        with self._lock:
            row = self._store.get(operation_key)
            if row is None or row.owner_token != owner_token or row.status != HTTP_IDEMPOTENCY_STATUS_CLAIMING:
                return False
            row.claim_expires_at = now + self._claim_ttl_seconds
            return True

    def complete(self, *, operation_key: str, owner_token: str, response: ReplayResponse) -> bool:
        now = self._clock()
        with self._lock:
            row = self._store.get(operation_key)
            if row is None or row.owner_token != owner_token or row.status != HTTP_IDEMPOTENCY_STATUS_CLAIMING:
                return False
            row.status = HTTP_IDEMPOTENCY_STATUS_COMPLETED
            row.response = response
            row.expires_at = now + self._receipt_ttl_seconds
            return True

    def release(self, *, operation_key: str, owner_token: str) -> bool:
        with self._lock:
            row = self._store.get(operation_key)
            if row is None or row.owner_token != owner_token or row.status != HTTP_IDEMPOTENCY_STATUS_CLAIMING:
                return False
            del self._store[operation_key]
            return True
