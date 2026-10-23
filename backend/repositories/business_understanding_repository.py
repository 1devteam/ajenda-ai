"""Tenant-explicit persistence mechanics for business understanding."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.business_understanding import BusinessNeedAssessment, BusinessNeedRevision, BusinessObservation


class BusinessNeedRevisionConflict(RuntimeError):
    """Raised when an append request was based on a stale need revision."""

    def __init__(self, *, expected_revision: int, current_revision: int) -> None:
        super().__init__("business need revision conflict")
        self.expected_revision = expected_revision
        self.current_revision = current_revision


class BusinessUnderstandingRepository:
    """Append-only observations and need revisions; callers own transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_observation(self, observation: BusinessObservation) -> BusinessObservation:
        self._session.add(observation)
        self._session.flush()
        self._session.refresh(observation)
        return observation

    def get_observation_for_tenant(self, *, observation_id: uuid.UUID, tenant_id: str) -> BusinessObservation | None:
        return self._session.scalar(
            select(BusinessObservation).where(
                BusinessObservation.id == observation_id,
                BusinessObservation.tenant_id == tenant_id,
            )
        )

    def list_observations_for_tenant(self, *, tenant_id: str, limit: int = 100) -> list[BusinessObservation]:
        return list(
            self._session.scalars(
                select(BusinessObservation)
                .where(BusinessObservation.tenant_id == tenant_id)
                .order_by(BusinessObservation.observed_at.desc(), BusinessObservation.id.desc())
                .limit(limit)
            )
        )

    def get_need_revision_for_tenant(
        self, *, need_id: str, revision: int, tenant_id: str
    ) -> BusinessNeedRevision | None:
        return self._session.scalar(
            select(BusinessNeedRevision).where(
                BusinessNeedRevision.tenant_id == tenant_id,
                BusinessNeedRevision.need_id == need_id,
                BusinessNeedRevision.revision == revision,
            )
        )

    def get_latest_need_for_tenant(self, *, need_id: str, tenant_id: str) -> BusinessNeedRevision | None:
        return self._session.scalar(
            select(BusinessNeedRevision)
            .where(BusinessNeedRevision.tenant_id == tenant_id, BusinessNeedRevision.need_id == need_id)
            .order_by(desc(BusinessNeedRevision.revision))
            .limit(1)
        )

    def list_latest_needs_for_tenant(self, *, tenant_id: str, limit: int = 100) -> list[BusinessNeedRevision]:
        rows = list(
            self._session.scalars(
                select(BusinessNeedRevision)
                .where(BusinessNeedRevision.tenant_id == tenant_id)
                .order_by(BusinessNeedRevision.need_id, desc(BusinessNeedRevision.revision))
            )
        )
        latest: dict[str, BusinessNeedRevision] = {}
        for row in rows:
            latest.setdefault(row.need_id, row)
        return list(latest.values())[:limit]

    def add_assessment(self, assessment: BusinessNeedAssessment) -> BusinessNeedAssessment:
        with self._session.begin_nested():
            self._session.add(assessment)
            self._session.flush()
        self._session.refresh(assessment)
        return assessment

    def get_assessment_by_fingerprint_for_tenant(
        self, *, tenant_id: str, need_id: str, need_revision: int, fingerprint: str
    ) -> BusinessNeedAssessment | None:
        """Return an identical assessment so retries do not create duplicates."""
        return self._session.scalar(
            select(BusinessNeedAssessment).where(
                BusinessNeedAssessment.tenant_id == tenant_id,
                BusinessNeedAssessment.need_id == need_id,
                BusinessNeedAssessment.need_revision == need_revision,
                BusinessNeedAssessment.assessment_fingerprint == fingerprint,
            )
        )

    def get_assessment_for_tenant(self, *, assessment_id: uuid.UUID, tenant_id: str) -> BusinessNeedAssessment | None:
        return self._session.scalar(
            select(BusinessNeedAssessment).where(
                BusinessNeedAssessment.id == assessment_id,
                BusinessNeedAssessment.tenant_id == tenant_id,
            )
        )

    def append_need_revision(
        self,
        *,
        tenant_id: str,
        need_id: str,
        expected_revision: int,
        values: dict[str, Any],
    ) -> BusinessNeedRevision:
        """Lock the latest revision and append exactly one next revision.

        The revision check and append occur in the caller's transaction.  The
        unique tenant/need/revision constraint provides the database boundary
        for a concurrent first revision as well.
        """

        latest = self._session.scalar(
            select(BusinessNeedRevision)
            .where(BusinessNeedRevision.tenant_id == tenant_id, BusinessNeedRevision.need_id == need_id)
            .order_by(desc(BusinessNeedRevision.revision))
            .limit(1)
            .with_for_update()
        )
        current_revision = latest.revision if latest is not None else 0
        if current_revision != expected_revision:
            raise BusinessNeedRevisionConflict(
                expected_revision=expected_revision,
                current_revision=current_revision,
            )
        row = BusinessNeedRevision(
            tenant_id=tenant_id,
            need_id=need_id,
            revision=current_revision + 1,
            previous_revision_id=latest.id if latest is not None else None,
            **values,
        )
        try:
            # A savepoint keeps a concurrent first-revision uniqueness race
            # from poisoning the caller-owned transaction.
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            concurrent = self.get_latest_need_for_tenant(tenant_id=tenant_id, need_id=need_id)
            if concurrent is not None:
                raise BusinessNeedRevisionConflict(
                    expected_revision=expected_revision,
                    current_revision=concurrent.revision,
                ) from exc
            raise
        self._session.refresh(row)
        return row
