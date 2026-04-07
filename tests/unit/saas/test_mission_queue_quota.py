"""Unit tests for per-task quota enforcement on the mission queue route.

Covers the bug where quota was checked once per call to POST /missions/{id}/queue
regardless of how many tasks queue_all_planned_tasks() would actually enqueue.
A mission with N planned tasks must consume N quota units, not 1.

Also covers the extended check_and_record_task_creation(count=N) API on
QuotaEnforcementService.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.services.quota_enforcement import (
    QuotaEnforcementService,
    QuotaExceededError,
)

# ---------------------------------------------------------------------------
# Helpers (mirrors test_quota_enforcement.py conventions)
# ---------------------------------------------------------------------------


def _make_tenant(plan: str = "free", status: str = "active"):
    t = MagicMock()
    t.plan = plan
    t.status = status
    return t


def _make_plan(max_tasks: int = 50):
    p = MagicMock()
    p.max_tasks_per_month = max_tasks
    p.allows_feature = lambda f: False
    return p


def _make_usage(tasks: int = 0):
    u = MagicMock()
    u.tasks_created = tasks
    return u


def _make_service(tenant, plan, usage) -> QuotaEnforcementService:
    db = MagicMock()
    svc = QuotaEnforcementService(db)
    repo = MagicMock()
    repo.get_active.return_value = tenant
    repo.get_plan.return_value = plan
    repo.get_or_create_usage.return_value = usage
    repo.increment_usage.return_value = None
    svc._tenants = repo
    return svc


# ---------------------------------------------------------------------------
# QuotaEnforcementService.check_and_record_task_creation(count=N)
# ---------------------------------------------------------------------------


class TestCheckAndRecordTaskCreationWithCount:
    """Tests for the extended count parameter on check_and_record_task_creation."""

    def test_single_task_default_count_still_works(self):
        """Existing single-task callers must continue to work without changes."""
        svc = _make_service(_make_tenant(), _make_plan(max_tasks=50), _make_usage(tasks=10))
        svc.check_and_record_task_creation(uuid.uuid4())  # count defaults to 1
        svc._tenants.increment_usage.assert_called_once_with(
            svc._tenants.increment_usage.call_args.args[0],
            field="tasks_created",
            amount=1,
        )

    def test_batch_of_five_increments_by_five(self):
        """Queuing 5 tasks at once must increment the counter by 5."""
        svc = _make_service(_make_tenant(), _make_plan(max_tasks=50), _make_usage(tasks=10))
        tenant_id = uuid.uuid4()
        svc.check_and_record_task_creation(tenant_id, count=5)
        call_kwargs = svc._tenants.increment_usage.call_args
        assert call_kwargs.kwargs.get("amount") == 5
        assert call_kwargs.kwargs.get("field") == "tasks_created"

    def test_blocks_when_batch_would_exceed_limit(self):
        """If usage=48 and count=5 and limit=50, the batch must be rejected."""
        svc = _make_service(_make_tenant("free"), _make_plan(max_tasks=50), _make_usage(tasks=48))
        with pytest.raises(QuotaExceededError) as exc_info:
            svc.check_and_record_task_creation(uuid.uuid4(), count=5)
        err = exc_info.value
        assert err.field == "tasks_per_month"
        assert err.limit == 50
        assert err.current == 48  # reports current usage, not projected

    def test_allows_batch_that_exactly_fills_remaining_quota(self):
        """usage=45, count=5, limit=50 → exactly at limit after → allowed."""
        svc = _make_service(_make_tenant("free"), _make_plan(max_tasks=50), _make_usage(tasks=45))
        svc.check_and_record_task_creation(uuid.uuid4(), count=5)  # should not raise
        svc._tenants.increment_usage.assert_called_once()

    def test_blocks_when_single_task_would_exceed_limit(self):
        """Regression: single-task path (count=1) still blocks at limit."""
        svc = _make_service(_make_tenant("free"), _make_plan(max_tasks=50), _make_usage(tasks=50))
        with pytest.raises(QuotaExceededError):
            svc.check_and_record_task_creation(uuid.uuid4(), count=1)

    def test_unlimited_plan_never_blocks_large_batch(self):
        """Enterprise plan (-1 limit) must never block any batch size."""
        svc = _make_service(
            _make_tenant("enterprise"),
            _make_plan(max_tasks=-1),
            _make_usage(tasks=999_999),
        )
        svc.check_and_record_task_creation(uuid.uuid4(), count=1_000)  # should not raise

    def test_invalid_count_raises_value_error(self):
        """count=0 is nonsensical and must raise ValueError immediately."""
        svc = _make_service(_make_tenant(), _make_plan(), _make_usage())
        with pytest.raises(ValueError, match="count must be >= 1"):
            svc.check_and_record_task_creation(uuid.uuid4(), count=0)

    def test_negative_count_raises_value_error(self):
        """Negative count must also raise ValueError."""
        svc = _make_service(_make_tenant(), _make_plan(), _make_usage())
        with pytest.raises(ValueError, match="count must be >= 1"):
            svc.check_and_record_task_creation(uuid.uuid4(), count=-3)

    def test_unknown_plan_fails_open_for_batch(self):
        """Unknown plan (None from repo) must not block even for large batches."""
        db = MagicMock()
        svc = QuotaEnforcementService(db)
        repo = MagicMock()
        repo.get_active.return_value = _make_tenant("unknown_plan")
        repo.get_plan.return_value = None
        svc._tenants = repo
        svc.check_and_record_task_creation(uuid.uuid4(), count=100)  # should not raise


# ---------------------------------------------------------------------------
# Mission queue route: quota enforcement per-task (not per-call)
# ---------------------------------------------------------------------------


class TestMissionQueueRouteQuotaEnforcement:
    """Tests that the mission queue route passes the correct task count to quota."""

    def _make_planned_task(self, tenant_id: str, mission_id: uuid.UUID) -> MagicMock:
        t = MagicMock()
        t.id = uuid.uuid4()
        t.tenant_id = tenant_id
        t.mission_id = mission_id
        t.status = "planned"
        return t

    def test_quota_checked_with_correct_task_count(self):
        """POST /missions/{id}/queue must pass count=N (not count=1) to quota service."""
        from backend.api.routes.mission import queue_mission

        tenant_id = str(uuid.uuid4())
        mission_id = uuid.uuid4()
        tenant_uuid = uuid.UUID(tenant_id)

        # Build 3 planned tasks for the mission
        tasks = [self._make_planned_task(tenant_id, mission_id) for _ in range(3)]

        db = MagicMock()
        queue = MagicMock()
        request = MagicMock()

        quota_svc = MagicMock()
        executor = MagicMock()
        executor.queue_all_planned_tasks.return_value = [t.id for t in tasks]

        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = tasks

        with (
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
            patch("backend.api.routes.mission.MissionExecutor", return_value=executor),
            patch("backend.api.routes.mission.ExecutionCoordinator"),
        ):
            result = queue_mission(
                mission_id=mission_id,
                request=request,
                tenant_id=tenant_uuid,
                db=db,
                queue=queue,
            )

        # Quota must be called with count=3, not count=1
        quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_uuid, count=3)
        assert len(result["queued_task_ids"]) == 3

    def test_empty_mission_skips_quota_and_returns_empty(self):
        """A mission with no planned tasks must skip quota entirely and return []."""
        from backend.api.routes.mission import queue_mission

        tenant_id = str(uuid.uuid4())
        mission_id = uuid.uuid4()

        db = MagicMock()
        queue = MagicMock()
        request = MagicMock()

        quota_svc = MagicMock()
        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = []  # no tasks

        tenant_uuid = uuid.UUID(tenant_id)
        with (
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        ):
            result = queue_mission(
                mission_id=mission_id,
                request=request,
                tenant_id=tenant_uuid,
                db=db,
                queue=queue,
            )

        quota_svc.check_and_record_task_creation.assert_not_called()
        assert result == {"queued_task_ids": []}

    def test_quota_exceeded_returns_429_with_correct_task_count(self):
        """When quota is exceeded for N tasks, the route must return 429."""
        from fastapi import HTTPException

        from backend.api.routes.mission import queue_mission

        tenant_id = str(uuid.uuid4())
        mission_id = uuid.uuid4()

        tasks = [self._make_planned_task(tenant_id, mission_id) for _ in range(10)]

        db = MagicMock()
        queue = MagicMock()
        request = MagicMock()

        quota_svc = MagicMock()
        quota_svc.check_and_record_task_creation.side_effect = QuotaExceededError(
            field="tasks_per_month",
            limit=50,
            current=45,
            plan="free",
        )
        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = tasks

        tenant_uuid = uuid.UUID(tenant_id)
        with (
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
        ):
            with pytest.raises(HTTPException) as exc_info:
                queue_mission(
                    mission_id=mission_id,
                    request=request,
                    tenant_id=tenant_uuid,
                    db=db,
                    queue=queue,
                )

        assert exc_info.value.status_code == 429
        detail = exc_info.value.detail
        assert detail["code"] == "QUOTA_EXCEEDED"
        assert detail["field"] == "tasks_per_month"
        assert detail["limit"] == 50
        assert detail["current"] == 45

    def test_only_planned_tasks_counted_for_quota(self):
        """Tasks in non-PLANNED states must not be counted toward the quota check."""
        from backend.api.routes.mission import queue_mission

        tenant_id = str(uuid.uuid4())
        mission_id = uuid.uuid4()

        planned = self._make_planned_task(tenant_id, mission_id)
        planned.status = "planned"

        already_queued = self._make_planned_task(tenant_id, mission_id)
        already_queued.status = "queued"  # already in the queue — not counted

        completed = self._make_planned_task(tenant_id, mission_id)
        completed.status = "completed"  # already done — not counted

        db = MagicMock()
        queue = MagicMock()
        request = MagicMock()

        quota_svc = MagicMock()
        executor = MagicMock()
        executor.queue_all_planned_tasks.return_value = [planned.id]

        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = [planned, already_queued, completed]

        tenant_uuid = uuid.UUID(tenant_id)
        with (
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
            patch("backend.api.routes.mission.MissionExecutor", return_value=executor),
            patch("backend.api.routes.mission.ExecutionCoordinator"),
        ):
            queue_mission(
                mission_id=mission_id,
                request=request,
                tenant_id=tenant_uuid,
                db=db,
                queue=queue,
            )

        # Only 1 planned task — quota must be called with count=1, not count=3
        call_args = quota_svc.check_and_record_task_creation.call_args
        assert call_args.kwargs.get("count") == 1
