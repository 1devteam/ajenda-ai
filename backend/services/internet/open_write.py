"""Open-write policy for public-web mutations (forms / generic POST).

Separate from connector OAuth writes. Flag-gated, rate-limited, HTTPS-only,
idempotency required (claim-before-send), NetworkEgressAuthority only.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend.rate_limit.limiter import RateLimitDecision, RateLimiter, RateLimitKey
from backend.repositories.email_send_idempotency_repository import EmailSendIdempotencyRepository
from backend.services.internet.modes import InternetAccessMode
from backend.services.internet.url_safety import reject_credentialed_url
from backend.services.network_egress import get_default_network_egress_authority

WriteMethod = Literal["POST", "PUT", "PATCH"]
OPEN_WRITE_ACTION = "web.open_write"
_OPEN_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})
# Rate limit is tenant-scoped — principal is a fixed policy bucket, never worker_id.
_TENANT_RATE_PRINCIPAL = "open_write_policy"
_lock = threading.Lock()
_limiter: RateLimiter | None = None
# Process-local claim table for tests / single-process; workers with session_factory use durable DB.
_memory_claims: dict[tuple[str, str, str], dict[str, Any]] = {}
_memory_lock = threading.Lock()


class OpenWritePolicyError(ValueError):
    """Deterministic open-write policy denial."""


@dataclass(frozen=True, slots=True)
class OpenWriteResult:
    real: bool
    url: str
    method: str
    status_code: int | None
    body_text: str | None
    body_truncated: bool
    error: str | None
    rate_limit_remaining: int | None
    access_mode: InternetAccessMode = InternetAccessMode.OPEN_WRITE
    idempotency_decision: str | None = None
    idempotency_backend: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "real": self.real,
            "url": self.url,
            "method": self.method,
            "status_code": self.status_code,
            "body_text": self.body_text,
            "body_truncated": self.body_truncated,
            "error": self.error,
            "rate_limit_remaining": self.rate_limit_remaining,
            "access_mode": self.access_mode.value,
            "idempotency_decision": self.idempotency_decision,
            "idempotency_backend": self.idempotency_backend,
        }


def open_write_enabled() -> bool:
    try:
        from backend.app.config import get_settings

        return bool(get_settings().open_write_enabled)
    except Exception:
        import os

        return (os.environ.get("AJENDA_OPEN_WRITE_ENABLED") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }


def _max_per_hour() -> int:
    try:
        from backend.app.config import get_settings

        return int(get_settings().open_write_max_per_hour)
    except Exception:
        import os

        raw = (os.environ.get("AJENDA_OPEN_WRITE_MAX_PER_HOUR") or "20").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 20


def _get_limiter() -> RateLimiter:
    global _limiter
    with _lock:
        max_req = _max_per_hour()
        if _limiter is None or _limiter._max_requests != max_req:
            _limiter = RateLimiter(max_requests=max_req, window_seconds=3600)
        return _limiter


def reset_open_write_rate_limiter_for_tests() -> None:
    global _limiter
    with _lock:
        _limiter = None
    with _memory_lock:
        _memory_claims.clear()


def evaluate_open_write_rate_limit(*, tenant_id: str) -> RateLimitDecision:
    """Tenant-wide quota — do not key by worker_id.

    Note: this is process-local. Multi-replica workers need a shared backend
    (Redis) for hard cluster-wide caps; claim-before-send still prevents
    duplicate mutations across workers when session_factory is wired.
    """

    key = RateLimitKey(
        tenant_id=tenant_id,
        principal_id=_TENANT_RATE_PRINCIPAL,
        route=OPEN_WRITE_ACTION,
    )
    return _get_limiter().evaluate(key)


def _request_fingerprint(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    body_text: str | None,
) -> str:
    payload = {
        "method": method,
        "url": url,
        "headers": {k.lower(): headers[k] for k in sorted(headers, key=str.lower)},
        "json_body": json_body,
        "body_text": body_text,
    }
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _claim_memory(*, tenant_id: str, idempotency_key: str) -> tuple[str, dict[str, Any] | None]:
    key = (tenant_id, OPEN_WRITE_ACTION, idempotency_key)
    with _memory_lock:
        existing = _memory_claims.get(key)
        if existing is None:
            _memory_claims[key] = {"status": "claiming", "payload": None}
            return "newly_claimed", None
        if existing.get("status") == "completed":
            payload = existing.get("payload")
            return "replayed", dict(payload) if isinstance(payload, dict) else {}
        return "in_flight", None


def _complete_memory(*, tenant_id: str, idempotency_key: str, payload: dict[str, Any]) -> None:
    key = (tenant_id, OPEN_WRITE_ACTION, idempotency_key)
    with _memory_lock:
        _memory_claims[key] = {"status": "completed", "payload": dict(payload)}


def _release_memory(*, tenant_id: str, idempotency_key: str) -> None:
    key = (tenant_id, OPEN_WRITE_ACTION, idempotency_key)
    with _memory_lock:
        current = _memory_claims.get(key)
        if current and current.get("status") == "claiming":
            del _memory_claims[key]


def _claim_durable(
    *,
    session_factory: Callable[[], Session],
    tenant_id: str,
    idempotency_key: str,
) -> tuple[str, dict[str, Any] | None]:
    session = session_factory()
    try:
        status, payload = EmailSendIdempotencyRepository(session).try_claim(
            tenant_id=tenant_id,
            action=OPEN_WRITE_ACTION,
            idempotency_key=idempotency_key,
        )
        session.commit()
        return status, payload
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _complete_durable(
    *,
    session_factory: Callable[[], Session],
    tenant_id: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> None:
    session = session_factory()
    try:
        EmailSendIdempotencyRepository(session).complete(
            tenant_id=tenant_id,
            action=OPEN_WRITE_ACTION,
            idempotency_key=idempotency_key,
            result_payload=payload,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _release_durable(
    *,
    session_factory: Callable[[], Session],
    tenant_id: str,
    idempotency_key: str,
    error_detail: str | None,
) -> None:
    session = session_factory()
    try:
        EmailSendIdempotencyRepository(session).release(
            tenant_id=tenant_id,
            action=OPEN_WRITE_ACTION,
            idempotency_key=idempotency_key,
            error_detail=error_detail,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def execute_open_write(
    *,
    tenant_id: str,
    url: str,
    method: str,
    idempotency_key: str,
    json_body: dict[str, Any] | None = None,
    body_text: str | None = None,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 10.0,
    session_factory: Callable[[], Session] | None = None,
) -> OpenWriteResult:
    """Policy gate + claim-before-send + egress POST/PUT/PATCH."""

    normalized_method = method.upper().strip()
    if normalized_method not in _OPEN_WRITE_METHODS:
        return OpenWriteResult(
            real=False,
            url=url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error="open_write only allows POST, PUT, or PATCH",
            rate_limit_remaining=None,
        )
    key = idempotency_key.strip()
    if not key:
        return OpenWriteResult(
            real=False,
            url=url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error="idempotency_key is required for open_write",
            rate_limit_remaining=None,
        )
    if not open_write_enabled():
        return OpenWriteResult(
            real=False,
            url=url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error="open_write disabled (set AJENDA_OPEN_WRITE_ENABLED=true)",
            rate_limit_remaining=None,
        )
    try:
        safe_url = reject_credentialed_url(url, action_name="web.open_write")
    except ValueError as exc:
        return OpenWriteResult(
            real=False,
            url=url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error=str(exc),
            rate_limit_remaining=None,
        )

    request_headers = dict(headers or {})
    request_headers.setdefault("User-Agent", "AjendaInternet/1.0 (+open_write)")
    request_headers["X-Ajenda-Idempotency-Key"] = key[:200]
    content: bytes | None = None
    json_payload = json_body
    if body_text is not None and json_body is None:
        content = body_text.encode("utf-8")
        request_headers.setdefault("Content-Type", "text/plain; charset=utf-8")

    request_fingerprint = _request_fingerprint(
        method=normalized_method,
        url=safe_url,
        headers=request_headers,
        json_body=json_payload,
        body_text=body_text if json_payload is None else None,
    )

    backend = "durable" if session_factory is not None else "memory"
    # Claim first so successful replays never burn / fail on quota.
    if session_factory is not None:
        claim_status, cached = _claim_durable(
            session_factory=session_factory,
            tenant_id=tenant_id,
            idempotency_key=key,
        )
    else:
        claim_status, cached = _claim_memory(tenant_id=tenant_id, idempotency_key=key)

    if claim_status == "replayed":
        cached = cached or {}
        prior_fp = cached.get("request_fingerprint")
        if isinstance(prior_fp, str) and prior_fp and prior_fp != request_fingerprint:
            return OpenWriteResult(
                real=False,
                url=safe_url,
                method=normalized_method,
                status_code=None,
                body_text=None,
                body_truncated=False,
                error="idempotency_key already used for a different open_write request",
                rate_limit_remaining=None,
                idempotency_decision="fingerprint_mismatch",
                idempotency_backend=backend,
            )
        return OpenWriteResult(
            real=bool(cached.get("real", True)),
            url=str(cached.get("url") or safe_url),
            method=str(cached.get("method") or normalized_method),
            status_code=cached.get("status_code") if isinstance(cached.get("status_code"), int) else None,
            body_text=str(cached["body_text"]) if isinstance(cached.get("body_text"), str) else None,
            body_truncated=bool(cached.get("body_truncated", False)),
            error=str(cached["error"]) if isinstance(cached.get("error"), str) else None,
            rate_limit_remaining=None,
            idempotency_decision="replayed",
            idempotency_backend=backend,
        )
    if claim_status == "in_flight":
        return OpenWriteResult(
            real=False,
            url=safe_url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error="open_write already claimed for this idempotency_key and is not yet finalized",
            rate_limit_remaining=None,
            idempotency_decision="in_flight",
            idempotency_backend=backend,
        )

    decision = evaluate_open_write_rate_limit(tenant_id=tenant_id)
    if not decision.allowed:
        # Release unused claim so a later hour can retry the same key.
        if session_factory is not None:
            try:
                _release_durable(
                    session_factory=session_factory,
                    tenant_id=tenant_id,
                    idempotency_key=key,
                    error_detail="rate_limited",
                )
            except Exception:
                pass
        else:
            _release_memory(tenant_id=tenant_id, idempotency_key=key)
        return OpenWriteResult(
            real=False,
            url=safe_url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error=f"open_write rate limit exceeded; retry_after_seconds={decision.retry_after_seconds}",
            rate_limit_remaining=0,
            idempotency_decision="released",
            idempotency_backend=backend,
        )

    try:
        _dest, response = get_default_network_egress_authority().request(
            method=normalized_method,
            url=safe_url,
            headers=request_headers,
            json_body=json_payload,
            content=content,
            timeout_seconds=min(timeout_seconds, 30.0),
            action_name="web.open_write",
            response_text_limit=8192,
        )
        result = OpenWriteResult(
            real=True,
            url=safe_url,
            method=normalized_method,
            status_code=response.status_code,
            body_text=response.body_text,
            body_truncated=response.body_truncated,
            error=None,
            rate_limit_remaining=decision.remaining,
            idempotency_decision="newly_claimed",
            idempotency_backend=backend,
        )
        payload = result.as_dict()
        payload["request_fingerprint"] = request_fingerprint
        if session_factory is not None:
            _complete_durable(
                session_factory=session_factory,
                tenant_id=tenant_id,
                idempotency_key=key,
                payload=payload,
            )
        else:
            _complete_memory(tenant_id=tenant_id, idempotency_key=key, payload=payload)
        return result
    except Exception as exc:
        # Ambiguous network outcomes must not re-send: finalize the claim as a
        # failed result so retries replay instead of mutating again.
        err = str(exc)
        result = OpenWriteResult(
            real=False,
            url=safe_url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error=err,
            rate_limit_remaining=decision.remaining,
            idempotency_decision="failed_finalized",
            idempotency_backend=backend,
        )
        payload = result.as_dict()
        payload["request_fingerprint"] = request_fingerprint
        try:
            if session_factory is not None:
                _complete_durable(
                    session_factory=session_factory,
                    tenant_id=tenant_id,
                    idempotency_key=key,
                    payload=payload,
                )
            else:
                _complete_memory(tenant_id=tenant_id, idempotency_key=key, payload=payload)
        except Exception:
            pass
        return result


__all__ = [
    "OPEN_WRITE_ACTION",
    "OpenWritePolicyError",
    "OpenWriteResult",
    "evaluate_open_write_rate_limit",
    "execute_open_write",
    "open_write_enabled",
    "reset_open_write_rate_limiter_for_tests",
]
