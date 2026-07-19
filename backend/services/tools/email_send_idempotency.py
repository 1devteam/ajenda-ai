"""Claim-before-send helpers for SMTP / platform_master email delivery.

The ability catalog requires idempotency for gtm.email_send external sends.
Gmail can pass Idempotency-Key to the provider; SMTP cannot. Callers must claim
before send_via_smtp and complete or release afterward.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend.repositories.email_send_idempotency_repository import EmailSendIdempotencyRepository

ClaimDecision = Literal["newly_claimed", "replayed", "in_flight", "rejected"]


@dataclass(slots=True, frozen=True)
class SmtpSendClaim:
    decision: ClaimDecision
    cached_output: dict[str, Any] | None = None
    error: str | None = None
    idempotency_key: str | None = None


def claim_smtp_send(
    *,
    session_factory: Callable[[], Session] | None,
    tenant_id: str,
    action: str,
    idempotency_key: str | None,
) -> SmtpSendClaim:
    """Durable pre-send claim. Fail closed when key or session is missing."""
    key = (idempotency_key or "").strip()
    if not key:
        return SmtpSendClaim(
            decision="rejected",
            error="smtp email send requires idempotency_key for deterministic replay protection",
        )
    if session_factory is None:
        return SmtpSendClaim(
            decision="rejected",
            error="smtp email send requires a durable session_factory for idempotency claim",
            idempotency_key=key,
        )

    session = session_factory()
    try:
        repo = EmailSendIdempotencyRepository(session)
        status, payload = repo.try_claim(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=key,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if status == "newly_claimed":
        return SmtpSendClaim(decision="newly_claimed", idempotency_key=key)
    if status == "replayed":
        return SmtpSendClaim(
            decision="replayed",
            cached_output=payload or {},
            idempotency_key=key,
        )
    return SmtpSendClaim(
        decision="in_flight",
        error="smtp email send already claimed for this idempotency_key and is not yet finalized",
        idempotency_key=key,
    )


def complete_smtp_send(
    *,
    session_factory: Callable[[], Session] | None,
    tenant_id: str,
    action: str,
    idempotency_key: str,
    result_payload: dict[str, Any],
) -> None:
    if session_factory is None:
        return
    session = session_factory()
    try:
        EmailSendIdempotencyRepository(session).complete(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=idempotency_key,
            result_payload=result_payload,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def release_smtp_send(
    *,
    session_factory: Callable[[], Session] | None,
    tenant_id: str,
    action: str,
    idempotency_key: str,
    error_detail: str | None = None,
) -> None:
    if session_factory is None:
        return
    session = session_factory()
    try:
        EmailSendIdempotencyRepository(session).release(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=idempotency_key,
            error_detail=error_detail,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
