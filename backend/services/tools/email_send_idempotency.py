"""Owner-safe claim-before-send helpers for SMTP delivery.

SMTP has no provider-side idempotency primitive. Ajenda therefore uses a
recoverable pre-send claim followed by a durable no-reclaim send fence. Once
that fence is crossed, an ambiguous transport outcome is never automatically
re-admitted for delivery.
"""

from __future__ import annotations

import threading
import uuid
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


# The durable receipt is the authority. This map only carries the random owner
# token between helper calls in one live worker execution so legacy call sites
# do not have to put ownership tokens into tool inputs or task metadata.
_owner_lock = threading.Lock()
_live_owners: dict[tuple[str, str, str], str] = {}


def _owner_key(*, tenant_id: str, action: str, idempotency_key: str) -> tuple[str, str, str]:
    return tenant_id, action, idempotency_key


def _remember_owner(*, tenant_id: str, action: str, idempotency_key: str, owner_token: str) -> None:
    with _owner_lock:
        _live_owners[_owner_key(tenant_id=tenant_id, action=action, idempotency_key=idempotency_key)] = owner_token


def _current_owner(*, tenant_id: str, action: str, idempotency_key: str) -> str | None:
    with _owner_lock:
        return _live_owners.get(_owner_key(tenant_id=tenant_id, action=action, idempotency_key=idempotency_key))


def _forget_owner(*, tenant_id: str, action: str, idempotency_key: str) -> None:
    with _owner_lock:
        _live_owners.pop(
            _owner_key(tenant_id=tenant_id, action=action, idempotency_key=idempotency_key),
            None,
        )


def claim_smtp_send(
    *,
    session_factory: Callable[[], Session] | None,
    tenant_id: str,
    action: str,
    idempotency_key: str | None,
) -> SmtpSendClaim:
    """Acquire a recoverable claim, then cross the durable SMTP send fence.

    The first transaction creates/takes over only an expired ``claiming`` row.
    A second transaction changes that owned row to ``sending`` before this
    function returns. Therefore any caller allowed to invoke SMTP is already
    behind the no-reclaim boundary.
    """
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

    owner_token = uuid.uuid4().hex
    session = session_factory()
    try:
        repo = EmailSendIdempotencyRepository(session)
        status, payload = repo.try_claim_smtp(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=key,
            owner_token=owner_token,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if status == "replayed":
        return SmtpSendClaim(
            decision="replayed",
            cached_output=payload or {},
            idempotency_key=key,
        )
    if status != "newly_claimed":
        return SmtpSendClaim(
            decision="in_flight",
            error=("smtp email send already has an active or delivery-ambiguous claim for this idempotency_key"),
            idempotency_key=key,
        )

    fence_session = session_factory()
    try:
        fenced = EmailSendIdempotencyRepository(fence_session).fence_smtp_send(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=key,
            owner_token=owner_token,
        )
        if not fenced:
            fence_session.rollback()
            return SmtpSendClaim(
                decision="in_flight",
                error="smtp send ownership changed before the durable send fence",
                idempotency_key=key,
            )
        fence_session.commit()
    except Exception:
        fence_session.rollback()
        raise
    finally:
        fence_session.close()

    _remember_owner(
        tenant_id=tenant_id,
        action=action,
        idempotency_key=key,
        owner_token=owner_token,
    )
    return SmtpSendClaim(decision="newly_claimed", idempotency_key=key)


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
    owner_token = _current_owner(
        tenant_id=tenant_id,
        action=action,
        idempotency_key=idempotency_key,
    )
    if owner_token is None:
        raise RuntimeError("smtp completion refused: no live owner token for fenced send")

    session = session_factory()
    try:
        completed = EmailSendIdempotencyRepository(session).complete_smtp_owned(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=idempotency_key,
            owner_token=owner_token,
            result_payload=result_payload,
        )
        if not completed:
            session.rollback()
            raise RuntimeError("smtp completion refused: durable claim owner/status mismatch")
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    _forget_owner(tenant_id=tenant_id, action=action, idempotency_key=idempotency_key)


def release_smtp_send(
    *,
    session_factory: Callable[[], Session] | None,
    tenant_id: str,
    action: str,
    idempotency_key: str,
    error_detail: str | None = None,
) -> None:
    """Release pre-send ownership or quarantine an ambiguous fenced outcome.

    Existing callers invoke this for transport failures. Since
    :func:`claim_smtp_send` fences before returning, those failures are treated
    as delivery-ambiguous and persisted as ``uncertain`` rather than deleting
    the receipt and enabling a duplicate SMTP retry.
    """
    if session_factory is None:
        return
    owner_token = _current_owner(
        tenant_id=tenant_id,
        action=action,
        idempotency_key=idempotency_key,
    )
    if owner_token is None:
        return

    session = session_factory()
    try:
        changed = EmailSendIdempotencyRepository(session).release_smtp_owned(
            tenant_id=tenant_id,
            action=action,
            idempotency_key=idempotency_key,
            owner_token=owner_token,
            error_detail=error_detail,
        )
        if not changed:
            session.rollback()
            raise RuntimeError("smtp release refused: durable claim owner/status mismatch")
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    _forget_owner(tenant_id=tenant_id, action=action, idempotency_key=idempotency_key)
