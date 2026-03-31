from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.lineage_record import LineageRecord


class LineageRecordRepository:
    """Append-only lineage storage for causal relationships."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, record: LineageRecord) -> LineageRecord:
        self._session.add(record)
        self._session.flush()
        self._session.refresh(record)
        return record

    def list_for_mission(self, mission_id: uuid.UUID) -> list[LineageRecord]:
        stmt = select(LineageRecord).where(LineageRecord.mission_id == mission_id)
        return list(self._session.scalars(stmt))
