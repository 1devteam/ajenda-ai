"""Repository for durable mission composition proposals."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.mission_composition_proposal import MissionCompositionProposal


class MissionCompositionProposalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(
        self,
        *,
        tenant_id: str,
        proposal_id: str,
        instruction: str,
        record_json: dict[str, Any],
        interpreter_version: str,
        components_active: list[str],
        ready_to_start: bool,
        actor_id: str | None = None,
        interpretation_thread_id: str | None = None,
        normalized_instruction: str | None = None,
        failure_reason: str | None = None,
        restatement_requirement: str | None = None,
        recognized_clauses: list[dict[str, Any]] | None = None,
        unmatched_clauses: list[dict[str, Any]] | None = None,
        unresolved_fields: list[str] | None = None,
        canonical_outcomes: list[str] | None = None,
        send_policy_json: dict[str, Any] | None = None,
        coverage_score: float | None = None,
        repeated_failure_count: int = 0,
        superseded_proposal_id: str | None = None,
        status: str = "interpretation_ready",
    ) -> MissionCompositionProposal:
        existing = self.get(tenant_id=tenant_id, proposal_id=proposal_id)
        now = datetime.now(tz=UTC)
        if existing is None:
            row = MissionCompositionProposal(
                id=f"mcp-{uuid.uuid4()}",
                tenant_id=tenant_id,
                proposal_id=proposal_id,
                actor_id=actor_id,
                interpretation_thread_id=interpretation_thread_id,
                instruction=instruction,
                normalized_instruction=normalized_instruction,
                interpreter_version=interpreter_version,
                components_active=list(components_active or []),
                record_json=record_json,
                ready_to_start=ready_to_start,
                failure_reason=failure_reason,
                restatement_requirement=restatement_requirement,
                recognized_clauses=list(recognized_clauses or []),
                unmatched_clauses=list(unmatched_clauses or []),
                unresolved_fields=list(unresolved_fields or []),
                canonical_outcomes=list(canonical_outcomes or []),
                send_policy_json=dict(send_policy_json or {}),
                coverage_score=coverage_score,
                repeated_failure_count=repeated_failure_count,
                superseded_proposal_id=superseded_proposal_id,
                status=status,
            )
            self._session.add(row)
            self._session.flush()
            return row

        existing.actor_id = actor_id
        existing.interpretation_thread_id = interpretation_thread_id
        existing.instruction = instruction
        existing.normalized_instruction = normalized_instruction
        existing.interpreter_version = interpreter_version
        existing.components_active = list(components_active or [])
        existing.record_json = record_json
        existing.ready_to_start = ready_to_start
        existing.failure_reason = failure_reason
        existing.restatement_requirement = restatement_requirement
        existing.recognized_clauses = list(recognized_clauses or [])
        existing.unmatched_clauses = list(unmatched_clauses or [])
        existing.unresolved_fields = list(unresolved_fields or [])
        existing.canonical_outcomes = list(canonical_outcomes or [])
        existing.send_policy_json = dict(send_policy_json or {})
        existing.coverage_score = coverage_score
        existing.repeated_failure_count = repeated_failure_count
        existing.superseded_proposal_id = superseded_proposal_id
        existing.status = status
        existing.updated_at = now
        self._session.add(existing)
        self._session.flush()
        return existing

    def get(self, *, tenant_id: str, proposal_id: str) -> MissionCompositionProposal | None:
        stmt = select(MissionCompositionProposal).where(
            MissionCompositionProposal.tenant_id == tenant_id,
            MissionCompositionProposal.proposal_id == proposal_id,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_for_update(self, *, tenant_id: str, proposal_id: str) -> MissionCompositionProposal | None:
        """Lock one tenant-scoped proposal for a single confirmation transaction."""

        stmt = (
            select(MissionCompositionProposal)
            .where(
                MissionCompositionProposal.tenant_id == tenant_id,
                MissionCompositionProposal.proposal_id == proposal_id,
            )
            .with_for_update()
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def mark_superseded(
        self,
        *,
        tenant_id: str,
        proposal_id: str,
        superseding_proposal_id: str,
    ) -> None:
        row = self.get(tenant_id=tenant_id, proposal_id=proposal_id)
        if row is None:
            return
        row.status = "superseded"
        row.superseding_proposal_id = superseding_proposal_id
        row.updated_at = datetime.now(tz=UTC)
        self._session.add(row)
        self._session.flush()

    def latest_failed_for_tenant(self, *, tenant_id: str, limit: int = 5) -> list[MissionCompositionProposal]:
        """Deprecated chronology lookup — prefer thread-scoped history."""

        stmt = (
            select(MissionCompositionProposal)
            .where(
                MissionCompositionProposal.tenant_id == tenant_id,
                MissionCompositionProposal.status.in_(
                    ("failed", "active", "interpretation_failed"),
                ),
                MissionCompositionProposal.ready_to_start.is_(False),
            )
            .order_by(MissionCompositionProposal.created_at.desc())
            .limit(limit)
        )
        return list(self._session.execute(stmt).scalars().all())

    def latest_interpretation_failures_for_thread(
        self,
        *,
        tenant_id: str,
        actor_id: str | None,
        interpretation_thread_id: str,
        limit: int = 5,
    ) -> list[MissionCompositionProposal]:
        """Only true interpretation failures for one actor+thread participate in escalation."""

        stmt = (
            select(MissionCompositionProposal)
            .where(
                MissionCompositionProposal.tenant_id == tenant_id,
                MissionCompositionProposal.interpretation_thread_id == interpretation_thread_id,
                MissionCompositionProposal.status == "interpretation_failed",
            )
            .order_by(MissionCompositionProposal.created_at.desc())
            .limit(limit)
        )
        if actor_id:
            stmt = stmt.where(MissionCompositionProposal.actor_id == actor_id)
        return list(self._session.execute(stmt).scalars().all())
