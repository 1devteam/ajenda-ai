"""In-process proposal store for compose → confirm.

Durable multi-worker proposal storage is a follow-up. Confirm also accepts a full
composition body so multi-process deploy does not depend on this cache alone.
"""

from __future__ import annotations

import threading
from typing import Any

from backend.services.mission_composition.contracts import MissionCompositionRecord

_LOCK = threading.Lock()
_PROPOSALS: dict[str, dict[str, Any]] = {}


def put_proposal(*, tenant_id: str, record: MissionCompositionRecord) -> None:
    with _LOCK:
        _PROPOSALS[record.proposal_id] = {
            "tenant_id": tenant_id,
            "record": record.model_dump(mode="json"),
        }


def get_proposal(*, tenant_id: str, proposal_id: str) -> MissionCompositionRecord | None:
    with _LOCK:
        payload = _PROPOSALS.get(proposal_id)
    if payload is None:
        return None
    if payload.get("tenant_id") != tenant_id:
        return None
    raw = payload.get("record")
    if not isinstance(raw, dict):
        return None
    return MissionCompositionRecord.model_validate(raw)


def clear_proposals_for_tests() -> None:
    with _LOCK:
        _PROPOSALS.clear()
