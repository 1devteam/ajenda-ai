from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent


class AuditEventRepository:
    """Append-only audit event storage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, event: AuditEvent) -> AuditEvent:
        self._session.add(event)
        self._session.flush()
        self._session.refresh(event)
        return event

    def append_unflushed(self, event: AuditEvent) -> AuditEvent:
        """Stage an audit fact in the caller's transaction without flushing."""

        self._session.add(event)
        return event

    def get_for_tenant(self, *, event_id: uuid.UUID, tenant_id: str) -> AuditEvent | None:
        """Read one immutable event without exposing another tenant's row."""

        stmt = select(AuditEvent).where(AuditEvent.id == event_id, AuditEvent.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def list_for_runtime_interaction_for_tenant(
        self,
        *,
        tenant_id: str,
        interaction_id: str,
    ) -> list[AuditEvent]:
        """Return only the tenant's evidence correlated to one interaction."""

        stmt = select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.category == "ui_interaction",
            AuditEvent.payload_json["runtime_evidence"]["correlation_id"].astext == interaction_id,
        )
        return list(self._session.scalars(stmt))

    def list_for_mission(self, mission_id: uuid.UUID) -> list[AuditEvent]:
        stmt = select(AuditEvent).where(AuditEvent.mission_id == mission_id)
        return list(self._session.scalars(stmt))

    def list_for_mission_for_tenant(self, *, mission_id: uuid.UUID, tenant_id: str) -> list[AuditEvent]:
        stmt = select(AuditEvent).where(
            AuditEvent.mission_id == mission_id,
            AuditEvent.tenant_id == tenant_id,
        )
        return list(self._session.scalars(stmt))

    def list_pre_mission_runtime_observations_for_tenant(
        self,
        *,
        tenant_id: str,
        correlation_ids: Sequence[str],
    ) -> list[AuditEvent]:
        """Read causal observations correlated to a confirmed mission proposal.

        Composition decisions are intentionally persisted before a mission row
        exists.  Keep this lookup tenant-scoped and limited to the observation
        category; the caller supplies only proposal IDs recovered from the
        mission's durable confirmation fact.  This is read-only and cannot
        authorize execution.
        """

        ids = tuple(sorted({value for value in correlation_ids if value}))
        if not ids:
            return []
        stmt = select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.mission_id.is_(None),
            AuditEvent.category == "runtime_decision",
            AuditEvent.payload_json["runtime_evidence"]["correlation_id"].astext.in_(ids),
        )
        return list(self._session.scalars(stmt))
