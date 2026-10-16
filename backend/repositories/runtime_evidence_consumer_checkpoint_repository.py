from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.runtime_evidence_consumer_checkpoint import RuntimeEvidenceConsumerCheckpoint


class RuntimeEvidenceConsumerCheckpointRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(
        self, *, tenant_id: str, mission_id: uuid.UUID, consumer_name: str
    ) -> RuntimeEvidenceConsumerCheckpoint:
        row = self._session.scalar(
            select(RuntimeEvidenceConsumerCheckpoint).where(
                RuntimeEvidenceConsumerCheckpoint.tenant_id == tenant_id,
                RuntimeEvidenceConsumerCheckpoint.mission_id == mission_id,
                RuntimeEvidenceConsumerCheckpoint.consumer_name == consumer_name,
            )
        )
        if row is None:
            row = RuntimeEvidenceConsumerCheckpoint(
                tenant_id=tenant_id, mission_id=mission_id, consumer_name=consumer_name
            )
            self._session.add(row)
            self._session.flush()
        return row

    def reset(self, *, tenant_id: str, mission_id: uuid.UUID, consumer_name: str) -> RuntimeEvidenceConsumerCheckpoint:
        row = self.get_or_create(tenant_id=tenant_id, mission_id=mission_id, consumer_name=consumer_name)
        row.last_event_id = None
        row.status = "pending"
        row.last_error = None
        row.result_json = {}
        self._session.flush()
        return row
