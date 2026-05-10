from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.outcome_review import OutcomeReview


class OutcomeReviewRepository:
    """Persistence contract for tenant-owned outcome review records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, review: OutcomeReview) -> OutcomeReview:
        self._session.add(review)
        self._session.flush()
        self._session.refresh(review)
        return review

    def get_for_tenant(self, *, review_id: uuid.UUID, tenant_id: str) -> OutcomeReview | None:
        stmt = select(OutcomeReview).where(OutcomeReview.id == review_id, OutcomeReview.tenant_id == tenant_id)
        return self._session.scalar(stmt)

    def list_for_mission(self, *, mission_id: uuid.UUID, tenant_id: str) -> list[OutcomeReview]:
        stmt = (
            select(OutcomeReview)
            .where(OutcomeReview.mission_id == mission_id, OutcomeReview.tenant_id == tenant_id)
            .order_by(OutcomeReview.created_at.asc())
        )
        return list(self._session.scalars(stmt))

    def update(self, review: OutcomeReview) -> OutcomeReview:
        self._session.add(review)
        self._session.flush()
        self._session.refresh(review)
        return review
