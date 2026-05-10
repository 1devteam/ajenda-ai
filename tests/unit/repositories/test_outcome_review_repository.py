from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from backend.domain.outcome_review import OutcomeReview
from backend.repositories.outcome_review_repository import OutcomeReviewRepository


def test_add_flushes_and_refreshes_outcome_review_record() -> None:
    record = OutcomeReview(
        tenant_id="tenant-a",
        mission_id=uuid.uuid4(),
        reviewer_type="operator",
        reviewer_source="qa",
        review_summary="Outcome reviewed.",
    )
    session = MagicMock()

    result = OutcomeReviewRepository(session).add(record)

    assert result is record
    session.add.assert_called_once_with(record)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(record)


def test_get_for_tenant_uses_tenant_scoped_query() -> None:
    tenant_id = str(uuid.uuid4())
    review_id = uuid.uuid4()
    record = OutcomeReview(
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        reviewer_type="system",
        reviewer_source="policy-check",
        review_summary="Reviewed.",
    )
    session = MagicMock()
    session.scalar.return_value = record

    result = OutcomeReviewRepository(session).get_for_tenant(review_id=review_id, tenant_id=tenant_id)

    assert result is record
    statement = session.scalar.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "outcome_reviews.id" in compiled
    assert "outcome_reviews.tenant_id" in compiled
    assert tenant_id in compiled


def test_list_for_mission_filters_by_tenant_and_mission() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    session = MagicMock()
    session.scalars.return_value = [MagicMock()]

    result = OutcomeReviewRepository(session).list_for_mission(mission_id=mission_id, tenant_id=tenant_id)

    assert result == [session.scalars.return_value[0]]
    statement = session.scalars.call_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "outcome_reviews.mission_id" in compiled
    assert "outcome_reviews.tenant_id" in compiled
    assert tenant_id in compiled


def test_update_flushes_and_refreshes_outcome_review_record() -> None:
    record = OutcomeReview(
        tenant_id="tenant-a",
        mission_id=uuid.uuid4(),
        reviewer_type="external",
        reviewer_source="auditor",
        review_summary="Review complete.",
    )
    session = MagicMock()

    result = OutcomeReviewRepository(session).update(record)

    assert result is record
    session.add.assert_called_once_with(record)
    session.flush.assert_called_once_with()
    session.refresh.assert_called_once_with(record)
