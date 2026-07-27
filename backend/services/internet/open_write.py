"""Open-write policy for public-web mutations (forms / generic POST).

Separate from connector OAuth writes. Flag-gated, rate-limited, HTTPS-only,
idempotency required, NetworkEgressAuthority only.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Literal

from backend.rate_limit.limiter import RateLimitDecision, RateLimiter, RateLimitKey
from backend.services.internet.modes import InternetAccessMode
from backend.services.network_egress import (
    NetworkEgressError,
    NetworkEgressResponse,
    VettedNetworkDestination,
    get_default_network_egress_authority,
)

WriteMethod = Literal["POST", "PUT", "PATCH"]
_OPEN_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH"})
_lock = threading.Lock()
_limiter: RateLimiter | None = None


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


def evaluate_open_write_rate_limit(*, tenant_id: str, principal_id: str = "runtime") -> RateLimitDecision:
    key = RateLimitKey(tenant_id=tenant_id, principal_id=principal_id or "runtime", route="web.open_write")
    return _get_limiter().evaluate(key)


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
    principal_id: str = "runtime",
) -> OpenWriteResult:
    """Policy gate + egress POST/PUT/PATCH. Never simulates success when blocked."""

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
    if not idempotency_key.strip():
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

    decision = evaluate_open_write_rate_limit(tenant_id=tenant_id, principal_id=principal_id)
    if not decision.allowed:
        return OpenWriteResult(
            real=False,
            url=url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error=f"open_write rate limit exceeded; retry_after_seconds={decision.retry_after_seconds}",
            rate_limit_remaining=0,
        )

    request_headers = dict(headers or {})
    request_headers.setdefault("User-Agent", "AjendaInternet/1.0 (+open_write)")
    request_headers["X-Ajenda-Idempotency-Key"] = idempotency_key.strip()[:200]
    content: bytes | None = None
    json_payload = json_body
    if body_text is not None and json_body is None:
        content = body_text.encode("utf-8")
        request_headers.setdefault("Content-Type", "text/plain; charset=utf-8")

    try:
        _dest, response = get_default_network_egress_authority().request(
            method=normalized_method,
            url=url,
            headers=request_headers,
            json_body=json_payload,
            content=content,
            timeout_seconds=min(timeout_seconds, 30.0),
            action_name="web.open_write",
            response_text_limit=8192,
        )
        return OpenWriteResult(
            real=True,
            url=url,
            method=normalized_method,
            status_code=response.status_code,
            body_text=response.body_text,
            body_truncated=response.body_truncated,
            error=None,
            rate_limit_remaining=decision.remaining,
        )
    except NetworkEgressError as exc:
        return OpenWriteResult(
            real=False,
            url=url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error=str(exc),
            rate_limit_remaining=decision.remaining,
        )
    except Exception as exc:
        return OpenWriteResult(
            real=False,
            url=url,
            method=normalized_method,
            status_code=None,
            body_text=None,
            body_truncated=False,
            error=str(exc),
            rate_limit_remaining=decision.remaining,
        )


# Re-export types used by tests/actions
__all__ = [
    "NetworkEgressResponse",
    "OpenWritePolicyError",
    "OpenWriteResult",
    "VettedNetworkDestination",
    "evaluate_open_write_rate_limit",
    "execute_open_write",
    "open_write_enabled",
    "reset_open_write_rate_limiter_for_tests",
]
