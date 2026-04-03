"""FastAPI dependency providers for service-layer objects.

These are the only sanctioned injection points for services into route handlers.
Services must NOT be instantiated directly inside route functions.

Removed: get_control_specialist — FoundationHealthChecker (formerly ControlSpecialist)
is an internal delegate of RuntimeGovernor and must not be injected into routes.
Routes that need health assessment must use RuntimeGovernor.evaluate().
"""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.queue.base import QueueAdapter
from backend.services.policy_guardian import PolicyGuardian
from backend.services.runtime_governor import RuntimeGovernor


def get_queue_adapter(request: Request) -> QueueAdapter:
    """Retrieve the queue adapter from app.state (set during lifespan startup)."""
    queue_adapter = getattr(request.app.state, "queue_adapter", None)
    if queue_adapter is None:
        raise RuntimeError(
            "Queue adapter not initialized. Ensure the app lifespan has completed startup."
        )
    return queue_adapter


def get_runtime_governor(db: Session = Depends(get_db_session)) -> RuntimeGovernor:
    """Provide a RuntimeGovernor for the current request's DB session."""
    return RuntimeGovernor(db)


def get_policy_guardian(db: Session = Depends(get_db_session)) -> PolicyGuardian:
    """Provide a PolicyGuardian for the current request's DB session."""
    return PolicyGuardian(db)
