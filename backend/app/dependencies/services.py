from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.app.dependencies.db import get_db_session
from backend.app.config import get_settings
from backend.queue import build_queue_adapter
from backend.queue.base import QueueAdapter
from backend.services.control_specialist import ControlSpecialist
from backend.services.policy_guardian import PolicyGuardian
from backend.services.runtime_governor import RuntimeGovernor


def get_queue_adapter(request: Request) -> QueueAdapter:
    queue_adapter = getattr(request.app.state, "queue_adapter", None)
    if queue_adapter is None:
        raise RuntimeError("Queue adapter not initialized")
    return queue_adapter


def get_control_specialist(db: Session = Depends(get_db_session)) -> ControlSpecialist:
    return ControlSpecialist(db)


def get_runtime_governor(db: Session = Depends(get_db_session)) -> RuntimeGovernor:
    return RuntimeGovernor(db)


def get_policy_guardian(db: Session = Depends(get_db_session)) -> PolicyGuardian:
    return PolicyGuardian(db)
