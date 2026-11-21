"""Deliver optional observations in a separate transaction after their source commits."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore

from sqlalchemy import event
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from backend.db.tenant_session import activate_tenant_session

logger = logging.getLogger(__name__)
_PENDING = "pending_runtime_observations"
_CAPACITY = BoundedSemaphore(64)
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="runtime-observer")
Observation = tuple[str, Callable[[Session], None]]


def observe_after_commit(session: Session, *, tenant_id: str, write: Callable[[Session], None]) -> None:
    """Stage a best-effort observation owned by the enclosing transaction."""
    if not isinstance(session, Session):
        return
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is not None:
        session.info.setdefault(_PENDING, {}).setdefault(transaction, []).append((tenant_id, write))


def _deliver(factory: sessionmaker[Session], observation: Observation) -> None:
    tenant_id, write = observation
    try:
        with factory() as session:
            activate_tenant_session(session, tenant_id)
            write(session)
            session.commit()
    except Exception as exc:
        logger.warning("runtime_observation_write_failed", extra={"error_type": type(exc).__name__})
    finally:
        _CAPACITY.release()


@event.listens_for(Session, "after_rollback")
def _discard_observations(session: Session) -> None:
    transaction = session.get_nested_transaction() or session.get_transaction()
    session.info.get(_PENDING, {}).pop(transaction, None)


@event.listens_for(Session, "after_commit")
def _publish_observations(session: Session) -> None:
    pending: dict[SessionTransaction, list[Observation]] = session.info.get(_PENDING, {})
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        return
    observations = pending.pop(transaction, [])
    if not observations:
        return
    if transaction.parent is not None:
        pending.setdefault(transaction.parent, []).extend(observations)
        return

    try:
        factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False, autoflush=False)
        for observation in observations:
            if not _CAPACITY.acquire(blocking=False):
                logger.warning("runtime_observation_capacity_exceeded")
                continue
            try:
                _EXECUTOR.submit(_deliver, factory, observation)
            except Exception:
                _CAPACITY.release()
                raise
    except Exception as exc:
        logger.warning("runtime_observation_delivery_unavailable", extra={"error_type": type(exc).__name__})
