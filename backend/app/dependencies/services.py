from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.queue.base import QueueAdapter
from backend.services.control_specialist import ControlSpecialist
from backend.services.policy_guardian import PolicyGuardian
from backend.services.runtime_governor import RuntimeGovernor

_DB_SESSION = Depends(get_db_session)


def get_queue_adapter(request: Request) -> QueueAdapter:
    queue_adapter = getattr(request.app.state, "queue_adapter", None)
    if queue_adapter is None:
        raise RuntimeError("Queue adapter not initialized")
    return queue_adapter


def get_control_specialist(db: Session = _DB_SESSION) -> ControlSpecialist:
    return ControlSpecialist(db)


def get_runtime_governor(db: Session = _DB_SESSION) -> RuntimeGovernor:
    return RuntimeGovernor(db)


def get_policy_guardian(db: Session = _DB_SESSION) -> PolicyGuardian:
    return PolicyGuardian(db)
