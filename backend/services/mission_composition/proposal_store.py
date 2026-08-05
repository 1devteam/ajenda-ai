"""Proposal store: in-process cache + durable SQL persistence.

Durable history is **required** for clarification-loop escalation and
supersession. When DB persistence fails, escalation is disabled (fail closed
for loop correctness claims — never claim multi-worker durable loops on memory).
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy.orm import Session

from backend.services.mission_composition.contracts import MissionCompositionRecord

_LOCK = threading.Lock()
_PROPOSALS: dict[str, dict[str, Any]] = {}


def put_proposal(
    *,
    tenant_id: str,
    record: MissionCompositionRecord,
    db: Session | None = None,
    actor_id: str | None = None,
    normalized_instruction: str | None = None,
    repeated_failure_count: int = 0,
    superseded_proposal_id: str | None = None,
    require_durable: bool = False,
) -> bool:
    """Persist proposal. Returns True when durable write succeeded (or not required)."""

    record_json: dict[str, Any] = record.model_dump(mode="json")
    payload: dict[str, Any] = {
        "tenant_id": tenant_id,
        "record": record_json,
    }
    with _LOCK:
        _PROPOSALS[record.proposal_id] = payload

    if db is None:
        return not require_durable
    try:
        from backend.repositories.mission_composition_proposal_repository import (
            MissionCompositionProposalRepository,
        )
    except Exception:
        return not require_durable

    intent = record.intent
    restatement = None
    unresolved: list[str] = []
    if record.clarifications:
        restatement = " ".join(c.question for c in record.clarifications)[:4000]
        unresolved = sorted({c.field for c in record.clarifications})

    status = record.proposal_status
    failure_reason = None
    if status == "interpretation_failed":
        failure_reason = unresolved[0] if unresolved else "interpretation_failed"
    elif not record.ready_to_start and status == "connection_required":
        failure_reason = "connection_required"
    elif not record.ready_to_start and status == "charter_blocked":
        failure_reason = "charter_blocked"

    recognized = [c.model_dump(mode="json") for c in intent.interpreted_clauses if c.status == "recognized"]
    unmatched = [c.model_dump(mode="json") for c in intent.unmatched_material_clauses]
    raw_instruction = record.raw_instruction or record.instruction
    normalized = normalized_instruction or record.normalized_instruction or intent.normalized_instruction

    try:
        MissionCompositionProposalRepository(db).upsert(
            tenant_id=tenant_id,
            proposal_id=record.proposal_id,
            instruction=raw_instruction,
            record_json=record_json,
            interpreter_version=intent.interpreter_version,
            components_active=list(intent.components_executed or intent.components_active),
            ready_to_start=record.ready_to_start,
            actor_id=actor_id,
            interpretation_thread_id=record.interpretation_thread_id,
            normalized_instruction=normalized,
            failure_reason=failure_reason,
            restatement_requirement=restatement,
            recognized_clauses=recognized,
            unmatched_clauses=unmatched,
            unresolved_fields=unresolved,
            canonical_outcomes=list(intent.requested_outcomes),
            send_policy_json=intent.send_policy.model_dump(mode="json"),
            coverage_score=intent.coverage_score,
            repeated_failure_count=repeated_failure_count,
            superseded_proposal_id=superseded_proposal_id,
            status=status,
        )
        db.commit()
        return True
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return False


def get_proposal(
    *,
    tenant_id: str,
    proposal_id: str,
    db: Session | None = None,
) -> MissionCompositionRecord | None:
    with _LOCK:
        payload = _PROPOSALS.get(proposal_id)
    if payload is not None and payload.get("tenant_id") == tenant_id:
        raw = payload.get("record")
        if isinstance(raw, dict):
            return MissionCompositionRecord.model_validate(raw)

    if db is None:
        return None
    try:
        from backend.repositories.mission_composition_proposal_repository import (
            MissionCompositionProposalRepository,
        )
    except Exception:
        return None
    try:
        row = MissionCompositionProposalRepository(db).get(tenant_id=tenant_id, proposal_id=proposal_id)
    except Exception:
        return None
    if row is None or not isinstance(row.record_json, dict):
        return None
    try:
        return MissionCompositionRecord.model_validate(row.record_json)
    except Exception:
        return None


def load_thread_failure_context(
    *,
    tenant_id: str,
    actor_id: str | None,
    interpretation_thread_id: str,
    db: Session | None,
) -> dict[str, Any] | None:
    """Backend-owned prior **interpretation** failure context for one thread only."""

    if db is None or not interpretation_thread_id.strip():
        return None
    try:
        from backend.repositories.mission_composition_proposal_repository import (
            MissionCompositionProposalRepository,
        )
    except Exception:
        return None
    try:
        rows = MissionCompositionProposalRepository(db).latest_interpretation_failures_for_thread(
            tenant_id=tenant_id,
            actor_id=actor_id,
            interpretation_thread_id=interpretation_thread_id,
            limit=5,
        )
    except Exception:
        return None
    if not rows:
        return None
    latest = rows[0]
    shared_fields: set[str] = set(latest.unresolved_fields or [])
    for row in rows[1:]:
        shared_fields &= set(row.unresolved_fields or [])
    return {
        "proposal_id": latest.proposal_id,
        "repeated_failure_count": int(latest.repeated_failure_count or 0) + 1,
        "unresolved_fields": sorted(shared_fields) if shared_fields else list(latest.unresolved_fields or []),
        "prior_instruction": latest.instruction,
        "restatement_requirement": latest.restatement_requirement,
        "interpretation_thread_id": interpretation_thread_id,
        "durable": True,
    }


def load_recent_failure_context(*, tenant_id: str, db: Session | None) -> dict[str, Any] | None:
    """Deprecated tenant-chronology lookup — disabled for correctness.

    Use load_thread_failure_context. Returning None prevents cross-actor contamination.
    """

    _ = (tenant_id, db)
    return None


def mark_superseded(
    *,
    tenant_id: str,
    proposal_id: str,
    superseding_proposal_id: str,
    db: Session | None,
) -> None:
    if db is None:
        return
    try:
        from backend.repositories.mission_composition_proposal_repository import (
            MissionCompositionProposalRepository,
        )

        MissionCompositionProposalRepository(db).mark_superseded(
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            superseding_proposal_id=superseding_proposal_id,
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def clear_proposals_for_tests() -> None:
    with _LOCK:
        _PROPOSALS.clear()
