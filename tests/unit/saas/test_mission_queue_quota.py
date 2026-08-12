"""Unit tests for per-task quota enforcement on the mission queue route.

Covers the bug where quota was checked once per call to POST /missions/{id}/queue
regardless of how many tasks queue_all_planned_tasks() would actually enqueue.
A mission with N planned tasks must consume N quota units, not 1.

Also covers the extended check_and_record_task_creation(count=N) API on
QuotaEnforcementService.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.services.execution_coordinator import CoordinationResult
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


class _AnyTenantId:
    def __eq__(self, _other: object) -> bool:
        return True

    def __ne__(self, _other: object) -> bool:
        return False


def _authorized_request() -> MagicMock:
    request = MagicMock()
    request.state.principal = SimpleNamespace(
        subject_id="test-user",
        tenant_id=_AnyTenantId(),
        roles=("tenant_admin",),
        permissions=frozenset(),
    )
    return request


# ---------------------------------------------------------------------------
# QuotaEnforcementService.check_and_record_task_creation(count=N)
# ---------------------------------------------------------------------------


class TestCheckAndRecordTaskCreationWithCount:
    """Tests for the extended count parameter on check_and_record_task_creation."""

    def test_single_task_default_count_still_works(self):
        """Existing single-task callers must continue to work without changes."""
        svc = _make_service(_make_tenant(), _make_plan(max_tasks=50), _make_usage(tasks=10))
        svc.check_and_record_task_creation(uuid.uuid4())
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
        assert err.current == 48

    def test_allows_batch_that_exactly_fills_remaining_quota(self):
        """usage=45, count=5, limit=50 → exactly at limit after → allowed."""
        svc = _make_service(_make_tenant("free"), _make_plan(max_tasks=50), _make_usage(tasks=45))
        svc.check_and_record_task_creation(uuid.uuid4(), count=5)
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
        svc.check_and_record_task_creation(uuid.uuid4(), count=1_000)

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
        svc.check_and_record_task_creation(uuid.uuid4(), count=100)


class TestMissionQueueCompatibilityWrapper:
    """Legacy route delegates all quota and eligibility decisions to canonical admission."""

    def test_projects_canonical_result_without_independent_queue_authority(self):
        from backend.api.routes.mission import queue_mission

        tenant_id = uuid.uuid4()
        mission_id = uuid.uuid4()
        db = MagicMock()
        queue = MagicMock()
        service = MagicMock()
        service.return_value.admit.return_value = {
            "queued_task_ids": ["queued"],
            "pending_review_task_ids": ["review"],
            "denied_tasks": [{"task_id": "denied", "state": "planned", "reason": "policy"}],
            "admission_status": "partially_admitted",
            "admitted_task_ids": ["queued"],
            "blocked_task_ids": ["review", "denied"],
            "blockers": [],
            "runtime_queue_admission": {},
        }

        with (
            patch("backend.api.routes.mission.MissionRuntimeQueueAdmissionService", service),
            patch("backend.services.mission_executor.MissionExecutor.queue_all_planned_tasks") as legacy_queue,
            patch("backend.api.routes.mission.TaskDispatcher") as dispatcher,
        ):
            result = queue_mission(
                mission_id=mission_id,
                request=_authorized_request(),
                tenant_id=tenant_id,
                db=db,
                queue=queue,
            )

        assert result == {
            "queued_task_ids": ["queued"],
            "pending_review_task_ids": ["review"],
            "denied_tasks": [{"task_id": "denied", "state": "planned", "reason": "policy"}],
        }
        service.return_value.admit.assert_called_once_with(mission_id=mission_id, tenant_id=tenant_id)
        legacy_queue.assert_not_called()
        dispatcher.assert_not_called()


class TestRuntimeQueueAdmissionQuotaEnforcement:
    """Tests that runtime queue admission charges quota only for materialized planned rows."""

    def _make_task(self, tenant_id: str, mission_id: uuid.UUID, status: str = "planned") -> MagicMock:
        task = MagicMock()
        task.id = uuid.uuid4()
        task.tenant_id = tenant_id
        task.mission_id = mission_id
        task.status = status
        return task

    def _make_mission(self, tenant_id: str, mission_id: uuid.UUID, task_ids: list[uuid.UUID]) -> SimpleNamespace:
        return SimpleNamespace(
            id=mission_id,
            tenant_id=tenant_id,
            metadata_json={
                "runtime_task_materialization": {
                    "schema_version": 1,
                    "materialization_status": "materialized",
                    "materialization_version": 1,
                    "created_execution_task_ids": [str(task_id) for task_id in task_ids],
                }
            },
        )

    def test_runtime_queue_admission_quota_counts_eligible_planned_tasks_only(self):
        from backend.api.routes.mission import runtime_queue_admission

        tenant_id = str(uuid.uuid4())
        tenant_uuid = uuid.UUID(tenant_id)
        mission_id = uuid.uuid4()
        planned_one = self._make_task(tenant_id, mission_id)
        planned_two = self._make_task(tenant_id, mission_id)
        queued = self._make_task(tenant_id, mission_id, status="queued")
        cancelled = self._make_task(tenant_id, mission_id, status="cancelled")
        foreign = self._make_task(str(uuid.uuid4()), mission_id)
        missing_id = uuid.uuid4()
        mission = self._make_mission(
            tenant_id, mission_id, [planned_one.id, queued.id, cancelled.id, foreign.id, missing_id, planned_two.id]
        )

        db = MagicMock()
        queue = MagicMock()
        request = _authorized_request()
        mission_repo = MagicMock()
        mission_repo.lock_for_tenant.return_value = mission
        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = [planned_one, queued, cancelled, foreign, planned_two]
        quota_svc = MagicMock()
        coordinator = MagicMock()
        coordinator.queue_task.side_effect = [
            CoordinationResult(ok=True, task_id=planned_one.id, state="queued"),
            CoordinationResult(ok=True, task_id=planned_two.id, state="queued"),
        ]

        with (
            patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
            patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
        ):
            result = runtime_queue_admission(
                mission_id=mission_id, request=request, tenant_id=tenant_uuid, db=db, queue=queue
            )

        quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_uuid, count=2)
        assert result["queued_task_ids"] == [str(planned_one.id), str(planned_two.id)]
        assert result["pending_review_task_ids"] == []
        assert result["denied_tasks"] == []
        assert result["admission_status"] == "partially_admitted"
        assert result["admitted_task_ids"] == [str(queued.id), str(planned_one.id), str(planned_two.id)]
        assert set(result["blocked_task_ids"]) == {str(cancelled.id), str(foreign.id), str(missing_id)}
        persisted = mission_repo.update_metadata.call_args.kwargs["metadata_json"]["runtime_queue_admission"]
        assert persisted["admission_status"] == "partially_admitted"
        assert [call.kwargs["task_id"] for call in coordinator.queue_task.call_args_list] == [
            planned_one.id,
            planned_two.id,
        ]

    def test_runtime_queue_admission_quota_denial_prevents_queueing(self):
        from backend.api.routes.mission import runtime_queue_admission

        tenant_id = str(uuid.uuid4())
        tenant_uuid = uuid.UUID(tenant_id)
        mission_id = uuid.uuid4()
        task = self._make_task(tenant_id, mission_id)
        mission = self._make_mission(tenant_id, mission_id, [task.id])
        mission_repo = MagicMock()
        mission_repo.lock_for_tenant.return_value = mission
        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = [task]
        quota_svc = MagicMock()
        quota_svc.check_and_record_task_creation.side_effect = QuotaExceededError(
            field="tasks_per_month", limit=50, current=50, plan="free"
        )
        coordinator = MagicMock()

        with (
            patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
            patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
        ):
            with pytest.raises(HTTPException) as exc_info:
                runtime_queue_admission(
                    mission_id=mission_id,
                    request=_authorized_request(),
                    tenant_id=tenant_uuid,
                    db=MagicMock(),
                    queue=MagicMock(),
                )

        assert exc_info.value.status_code == 402
        quota_svc.check_and_record_task_creation.assert_called_once_with(tenant_uuid, count=1)
        coordinator.queue_task.assert_not_called()

    def test_runtime_queue_admission_skips_non_planned_without_quota(self):
        from backend.api.routes.mission import runtime_queue_admission

        tenant_id = str(uuid.uuid4())
        tenant_uuid = uuid.UUID(tenant_id)
        mission_id = uuid.uuid4()
        queued = self._make_task(tenant_id, mission_id, status="queued")
        cancelled = self._make_task(tenant_id, mission_id, status="cancelled")
        mission = self._make_mission(tenant_id, mission_id, [queued.id, cancelled.id])
        mission_repo = MagicMock()
        mission_repo.lock_for_tenant.return_value = mission
        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = [queued, cancelled]
        quota_svc = MagicMock()
        coordinator = MagicMock()

        with (
            patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
            patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
        ):
            result = runtime_queue_admission(
                mission_id=mission_id,
                request=_authorized_request(),
                tenant_id=tenant_uuid,
                db=MagicMock(),
                queue=MagicMock(),
            )

        assert result["queued_task_ids"] == []
        assert result["pending_review_task_ids"] == []
        assert result["denied_tasks"] == []
        assert result["admission_status"] == "partially_admitted"
        assert result["admitted_task_ids"] == [str(queued.id)]
        assert result["blocked_task_ids"] == [str(cancelled.id)]
        quota_svc.check_and_record_task_creation.assert_not_called()
        coordinator.queue_task.assert_not_called()

    def test_runtime_queue_admission_preserves_success_when_later_task_raises(self):
        from backend.api.routes.mission import runtime_queue_admission

        tenant_id = str(uuid.uuid4())
        tenant_uuid = uuid.UUID(tenant_id)
        mission_id = uuid.uuid4()
        first_task = self._make_task(tenant_id, mission_id)
        second_task = self._make_task(tenant_id, mission_id)
        mission = self._make_mission(tenant_id, mission_id, [first_task.id, second_task.id])
        mission_repo = MagicMock()
        mission_repo.lock_for_tenant.return_value = mission
        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = [first_task, second_task]
        quota_svc = MagicMock()
        coordinator = MagicMock()
        coordinator.queue_task.side_effect = [
            CoordinationResult(ok=True, task_id=first_task.id, state="queued"),
            RuntimeError("queue path failed"),
        ]

        with (
            patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
            patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
        ):
            result = runtime_queue_admission(
                mission_id=mission_id,
                request=_authorized_request(),
                tenant_id=tenant_uuid,
                db=MagicMock(),
                queue=MagicMock(),
            )

        assert result["admission_status"] == "partially_admitted"
        assert result["queued_task_ids"] == [str(first_task.id)]
        assert result["admitted_task_ids"] == [str(first_task.id)]
        assert result["blocked_task_ids"] == [str(second_task.id)]
        assert result["blockers"][0]["code"] == "queue_task_failed"
        persisted = mission_repo.update_metadata.call_args.kwargs["metadata_json"]["runtime_queue_admission"]
        assert persisted["admission_status"] == "partially_admitted"
        assert persisted["queued_execution_task_ids"] == [str(first_task.id)]
        assert persisted["blocked_execution_task_ids"] == [str(second_task.id)]

    def test_runtime_queue_admission_returns_blocked_when_all_queue_calls_fail(self):
        from backend.api.routes.mission import runtime_queue_admission

        tenant_id = str(uuid.uuid4())
        tenant_uuid = uuid.UUID(tenant_id)
        mission_id = uuid.uuid4()
        first_task = self._make_task(tenant_id, mission_id)
        second_task = self._make_task(tenant_id, mission_id)
        mission = self._make_mission(tenant_id, mission_id, [first_task.id, second_task.id])
        mission_repo = MagicMock()
        mission_repo.lock_for_tenant.return_value = mission
        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = [first_task, second_task]
        quota_svc = MagicMock()
        coordinator = MagicMock()
        coordinator.queue_task.side_effect = [RuntimeError("first failed"), ValueError("second failed")]

        with (
            patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
            patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
        ):
            result = runtime_queue_admission(
                mission_id=mission_id,
                request=_authorized_request(),
                tenant_id=tenant_uuid,
                db=MagicMock(),
                queue=MagicMock(),
            )

        assert result["admission_status"] == "blocked"
        assert result["queued_task_ids"] == []
        assert result["admitted_task_ids"] == []
        assert set(result["blocked_task_ids"]) == {str(first_task.id), str(second_task.id)}
        assert coordinator.queue_task.call_count == 2
        persisted = mission_repo.update_metadata.call_args.kwargs["metadata_json"]["runtime_queue_admission"]
        assert persisted["admission_status"] == "blocked"

    def test_runtime_queue_admission_duplicate_post_is_idempotent_for_already_queued_rows(self):
        from backend.api.routes.mission import runtime_queue_admission

        tenant_id = str(uuid.uuid4())
        tenant_uuid = uuid.UUID(tenant_id)
        mission_id = uuid.uuid4()
        queued = self._make_task(tenant_id, mission_id, status="queued")
        mission = self._make_mission(tenant_id, mission_id, [queued.id])
        mission.metadata_json["runtime_queue_admission"] = {
            "schema_version": 1,
            "mission_id": str(mission_id),
            "tenant_id": tenant_id,
            "admission_status": "admitted",
            "admitted_execution_task_ids": [str(queued.id)],
        }
        mission_repo = MagicMock()
        mission_repo.lock_for_tenant.return_value = mission
        task_repo = MagicMock()
        task_repo.list_for_mission.return_value = [queued]
        quota_svc = MagicMock()
        coordinator = MagicMock()

        with (
            patch("backend.api.routes.mission.MissionRepository", return_value=mission_repo),
            patch("backend.api.routes.mission.ExecutionTaskRepository", return_value=task_repo),
            patch("backend.api.routes.mission.QuotaEnforcementService", return_value=quota_svc),
            patch("backend.api.routes.mission.ExecutionCoordinator", return_value=coordinator),
        ):
            result = runtime_queue_admission(
                mission_id=mission_id,
                request=_authorized_request(),
                tenant_id=tenant_uuid,
                db=MagicMock(),
                queue=MagicMock(),
            )

        assert result["admission_status"] == "admitted"
        assert result["queued_task_ids"] == []
        assert result["admitted_task_ids"] == [str(queued.id)]
        assert result["blocked_task_ids"] == []
        quota_svc.check_and_record_task_creation.assert_not_called()
        coordinator.queue_task.assert_not_called()
