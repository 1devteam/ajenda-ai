from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.retrieval_contract import RetrievalContract


class RetrievalContractRepository:
    """Persistence contract for tenant-owned retrieval and recall records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, retrieval: RetrievalContract) -> RetrievalContract:
        self._session.add(retrieval)
        self._session.flush()
        self._session.refresh(retrieval)
        return retrieval

    def get_for_tenant(self, *, retrieval_id: uuid.UUID, tenant_id: str) -> RetrievalContract | None:
        stmt = select(RetrievalContract).where(
            RetrievalContract.id == retrieval_id, RetrievalContract.tenant_id == tenant_id
        )
        return self._session.scalar(stmt)

    def list_for_mission(self, *, mission_id: uuid.UUID, tenant_id: str) -> list[RetrievalContract]:
        stmt = (
            select(RetrievalContract)
            .where(RetrievalContract.mission_id == mission_id, RetrievalContract.tenant_id == tenant_id)
            .order_by(RetrievalContract.created_at.asc())
        )
        return list(self._session.scalars(stmt))

    def update(self, retrieval: RetrievalContract) -> RetrievalContract:
        self._session.add(retrieval)
        self._session.flush()
        self._session.refresh(retrieval)
        return retrieval
