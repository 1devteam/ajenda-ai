"""Proposal store: in-process cache + optional durable SQL persistence.

Durable rows never grant runtime execution authority. Multi-worker confirm
still re-composes from instruction server-side.
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
) -> None:
    payload = {
        "tenant_id": tenant_id,
        "record": record.model_dump(mode="json"),
    }
    with _LOCK:
        _PROPOSALS[record.proposal_id] = payload

    if db is None:
        return
    try:
        from backend.repositories.mission_composition_proposal_repository import (
            MissionCompositionProposalRepository,
        )
    except Exception:
        return

    intent = record.intent
    restatement = None
    unresolved: list[str] = []
    if record.clarifications:
        restatement = " ".join(c.question for c in record.clarifications)[:4000]
        unresolved = sorted({c.field for c in record.clarifications})
    status = "ready" if record.ready_to_start else "failed"
    failure_reason = None
    if not record.ready_to_start:
        failure_reason = unresolved[0] if unresolved else "not_ready"

    recognized = [
        c.model_dump(mode="json")
        for c in intent.interpreted_clauses
        if c.status == "recognized"
    ]
    unmatched = [c.model_dump(mode="json") for c in intent.unmatched_material_clauses]

    try:
        MissionCompositionProposalRepository(db).upsert(
            tenant_id=tenant_id,
            proposal_id=record.proposal_id,
            instruction=record.instruction,
            record_json=payload["record"],
            interpreter_version=intent.interpreter_version,
            components_active=list(intent.components_active),
            ready_to_start=record.ready_to_start,
            actor_id=actor_id,
            normalized_instruction=normalized_instruction,
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
    except Exception:
        # Fail-open to in-memory: durable history must not break compose.
        try:
            db.rollback()
        except Exception:
            pass


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


def load_recent_failure_context(*, tenant_id: str, db: Session | None) -> dict[str, Any] | None:
    """Backend-owned prior failure context for restatement escalation (not client merge)."""

    if db is None:
        return None
    try:
        from backend.repositories.mission_composition_proposal_repository import (
            MissionCompositionProposalRepository,
        )
    except Exception:
        return None
    try:
        rows = MissionCompositionProposalRepository(db).latest_failed_for_tenant(tenant_id=tenant_id, limit=3)
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
    }


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
