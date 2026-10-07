from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.domain.assurance_snapshot import AssuranceSnapshot


class AssuranceSnapshotRepository:
    """Append-only tenant-scoped assurance history."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, snapshot: AssuranceSnapshot) -> AssuranceSnapshot:
        self._session.add(snapshot)
        self._session.flush()
        self._session.refresh(snapshot)
        return snapshot

    def list_for_tenant(self, *, tenant_id: str, limit: int = 100) -> list[AssuranceSnapshot]:
        stmt = (
            select(AssuranceSnapshot)
            .where(AssuranceSnapshot.tenant_id == tenant_id)
            .order_by(desc(AssuranceSnapshot.observed_at))
            .limit(max(1, min(limit, 500)))
        )
        return list(self._session.scalars(stmt))

    def latest_for_mission(
        self,
        *,
        tenant_id: str,
        mission_id: uuid.UUID,
    ) -> AssuranceSnapshot | None:
        stmt = (
            select(AssuranceSnapshot)
            .where(
                AssuranceSnapshot.tenant_id == tenant_id,
                AssuranceSnapshot.mission_id == mission_id,
            )
            .order_by(desc(AssuranceSnapshot.observed_at))
            .limit(1)
        )
        return self._session.scalar(stmt)

    def list_for_mission(
        self,
        *,
        tenant_id: str,
        mission_id: uuid.UUID,
        limit: int = 100,
    ) -> list[AssuranceSnapshot]:
        stmt = (
            select(AssuranceSnapshot)
            .where(
                AssuranceSnapshot.tenant_id == tenant_id,
                AssuranceSnapshot.mission_id == mission_id,
            )
            .order_by(desc(AssuranceSnapshot.observed_at))
            .limit(max(1, min(limit, 500)))
        )
        return list(self._session.scalars(stmt))
