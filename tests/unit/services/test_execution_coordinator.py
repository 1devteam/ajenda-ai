from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.domain.enums import ExecutionTaskState
from backend.queue.base import QueueOperationResult
from backend.services.execution_coordinator import ExecutionCoordinator
from backend.services.tools.schemas import side_effect_authorized, tool_invocation_sha256


def _allowed_decision() -> SimpleNamespace:
    return SimpleNamespace(execution_allowed=True, mode="NORMAL", reason=None)


def _policy_allowed() -> SimpleNamespace:
    return SimpleNamespace(allowed=True, reason=None)


def _task(*, tenant_id: str, status: str = ExecutionTaskState.PLANNED.value) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        mission_id=uuid.uuid4(),
        fleet_id=None,
        branch_id=None,
        status=status,
        metadata_json={"task_type": "echo"},
        compliance_category="operational",
        jurisdiction="US-ALL",
        requires_human_review=False,
    )


def _coordinator_with_task(*, task: SimpleNamespace, queue: MagicMock | None = None) -> ExecutionCoordinator:
    session = MagicMock()
    queue = queue or MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()
    coordinator._tasks.get.return_value = task
    coordinator._tasks.get_for_update.return_value = task
    coordinator._governor = MagicMock()
    coordinator._governor.evaluate.return_value = _allowed_decision()
    coordinator._policy = MagicMock()
    coordinator._policy.evaluate_task.return_value = _policy_allowed()
    coordinator._governance = MagicMock()
    coordinator._audit = MagicMock()
    return coordinator


def test_require_task_raises_when_task_missing() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()
    coordinator._tasks.get.return_value = None

    with pytest.raises(ValueError, match="task not found for tenant"):
        coordinator._require_task(task_id=uuid.uuid4(), tenant_id=str(uuid.uuid4()))


def test_require_task_raises_when_task_belongs_to_other_tenant() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()

    task = MagicMock()
    task.tenant_id = str(uuid.uuid4())
    coordinator._tasks.get.return_value = task

    with pytest.raises(ValueError, match="task not found for tenant"):
        coordinator._require_task(task_id=uuid.uuid4(), tenant_id=str(uuid.uuid4()))


def test_require_task_returns_task_for_matching_tenant() -> None:
    session = MagicMock()
    queue = MagicMock()
    coordinator = ExecutionCoordinator(session, queue)
    coordinator._tasks = MagicMock()

    tenant_id = str(uuid.uuid4())
    task = MagicMock()
    task.tenant_id = tenant_id
    coordinator._tasks.get.return_value = task

    result = coordinator._require_task(task_id=uuid.uuid4(), tenant_id=tenant_id)

    assert result is task


def test_queue_task_restores_previous_planned_state_when_enqueue_fails() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PLANNED.value)
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=False, reason="redis unavailable")
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="redis unavailable"):
        coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert task.status == ExecutionTaskState.PLANNED.value
    assert coordinator._session.flush.call_count == 2
    coordinator._audit.append.assert_not_called()


def test_queue_task_enqueues_after_transitioning_planned_task_to_queued() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PLANNED.value)
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    result = coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert result.ok is True
    assert result.state == ExecutionTaskState.QUEUED.value
    assert task.status == ExecutionTaskState.QUEUED.value
    queue.enqueue_task.assert_called_once()
    queued_message = queue.enqueue_task.call_args.args[0]
    assert queued_message.tenant_id == tenant_id
    assert queued_message.task_id == task.id
    assert queued_message.payload == task.metadata_json
    coordinator._audit.append.assert_called_once()


def test_queue_task_preserves_previous_retryable_state_on_enqueue_failure() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.FAILED.value)
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=False, reason=None)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="queue enqueue failed"):
        coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert task.status == ExecutionTaskState.FAILED.value
    coordinator._audit.append.assert_not_called()


def test_approve_review_queues_pending_review_task() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PENDING_REVIEW.value)
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    result = coordinator.approve_review_and_queue(tenant_id=tenant_id, task_id=task.id, actor="admin-test")

    assert result.ok is True
    assert result.state == ExecutionTaskState.QUEUED.value
    coordinator._tasks.get_for_update.assert_called_once_with(task.id)
    queue.enqueue_task.assert_called_once()
    assert coordinator._governance.append.call_args.args[0].event_type == "human_review_approved"
    assert coordinator._audit.append.call_count == 2


def test_side_effect_task_requires_review_then_approval_issues_exact_action_grant() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PLANNED.value)
    task.metadata_json = {
        "task_type": "tool.invoke",
        "tool_invocation": {
            "schema_version": 1,
            "action": "gtm.email_send",
            "input": {"to": "lead@example.com", "subject": "Hello", "body": "Draft"},
        },
    }
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    review = coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert review.ok is False
    assert task.status == ExecutionTaskState.PENDING_REVIEW.value
    queue.enqueue_task.assert_not_called()
    coordinator._tasks.get_for_update.return_value = task

    approved = coordinator.approve_review_and_queue(
        tenant_id=tenant_id,
        task_id=task.id,
        actor="admin:user-123",
        approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    assert approved.ok is True
    grant = task.metadata_json["execution_constraints"]["side_effect_authorization"]
    assert grant["schema_version"] == 2
    assert grant["tenant_id"] == tenant_id
    assert grant["task_id"] == str(task.id)
    assert grant["allowed_action"] == "gtm.email_send"
    assert grant["invocation_sha256"].startswith("sha256:")
    assert grant["reason"] == "human_review_approved"
    assert grant["approved_by"] == "admin:user-123"
    assert grant["revoked_at"] is None
    queued = queue.enqueue_task.call_args.args[0]
    assert queued.payload == task.metadata_json
    assert side_effect_authorized(
        task.metadata_json,
        "gtm.email_send",
        tenant_id=tenant_id,
        task_id=task.id,
    )

    revoked = coordinator.revoke_side_effect_approval(
        tenant_id=tenant_id,
        task_id=task.id,
        actor="admin:user-123",
        reason="recipient requested cancellation",
    )

    assert revoked.reason == "approval_revoked"
    revoked_grant = task.metadata_json["execution_constraints"]["side_effect_authorization"]
    assert revoked_grant["revoked_by"] == "admin:user-123"
    assert revoked_grant["revocation_reason"] == "recipient requested cancellation"
    assert not side_effect_authorized(
        task.metadata_json,
        "gtm.email_send",
        tenant_id=tenant_id,
        task_id=task.id,
    )


def test_side_effect_approval_binds_dependency_outputs_before_hashing_and_queueing() -> None:
    tenant_id = str(uuid.uuid4())
    mission_id = uuid.uuid4()
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PENDING_REVIEW.value)
    task.mission_id = mission_id
    task.metadata_json = {
        "task_type": "tool.invoke",
        "graph_node_key": "ability-record-write",
        "dependency_keys": ["ability-web-research", "ability-research-observe_contacts"],
        "input_bindings": [
            {
                "from_step": "ability-web-research",
                "output_path": "$.prospect_candidates",
                "input_path": "$.input.context.prospect_candidates",
            },
            {
                "from_step": "ability-research-observe_contacts",
                "output_path": "$.observed_contacts",
                "input_path": "$.input.context.observed_contacts",
            },
        ],
        "tool_invocation": {
            "schema_version": 1,
            "action": "record.write",
            "input": {
                "record_type": "contact",
                "data": {},
                "context": {
                    "binding_required": True,
                    "prospect_candidates": [],
                    "observed_contacts": [],
                },
            },
        },
    }
    prospect = {"prospect_id": "prospect-1", "company": "Acme Roofing", "domain": "acme.test"}
    contact = {"prospect_id": "prospect-1", "email": "owner@acme.test"}
    upstream_research = _task(tenant_id=tenant_id, status=ExecutionTaskState.COMPLETED.value)
    upstream_research.mission_id = mission_id
    upstream_research.metadata_json = {
        "graph_node_key": "ability-web-research",
        "handler_result": {"output": {"prospect_candidates": [prospect]}},
    }
    upstream_contacts = _task(tenant_id=tenant_id, status=ExecutionTaskState.COMPLETED.value)
    upstream_contacts.mission_id = mission_id
    upstream_contacts.metadata_json = {
        "graph_node_key": "ability-research-observe_contacts",
        "handler_result": {"output": {"observed_contacts": [contact]}},
    }
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)
    coordinator._tasks.list_for_mission_for_tenant.return_value = [
        upstream_research,
        upstream_contacts,
        task,
    ]

    result = coordinator.approve_review_and_queue(
        tenant_id=tenant_id,
        task_id=task.id,
        actor="admin:user-123",
        approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    assert result.ok is True
    invocation = task.metadata_json["tool_invocation"]
    assert invocation["input"]["context"]["prospect_candidates"] == [prospect]
    assert invocation["input"]["context"]["observed_contacts"] == [contact]
    grant = task.metadata_json["execution_constraints"]["side_effect_authorization"]
    assert grant["invocation_sha256"] == tool_invocation_sha256(invocation)
    assert side_effect_authorized(
        task.metadata_json,
        "record.write",
        tenant_id=tenant_id,
        task_id=task.id,
    )
    assert queue.enqueue_task.call_args.args[0].payload["tool_invocation"] == invocation


def test_side_effect_approval_fails_closed_before_dependencies_complete() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PENDING_REVIEW.value)
    task.metadata_json = {
        "task_type": "tool.invoke",
        "dependency_keys": ["ability-web-research"],
        "input_bindings": [
            {
                "from_step": "ability-web-research",
                "output_path": "$.prospect_candidates",
                "input_path": "$.input.context.prospect_candidates",
            }
        ],
        "tool_invocation": {
            "schema_version": 1,
            "action": "record.write",
            "input": {"record_type": "contact", "data": {}, "context": {"prospect_candidates": []}},
        },
    }
    coordinator = _coordinator_with_task(task=task)
    coordinator._tasks.list_for_mission_for_tenant.return_value = [task]

    with pytest.raises(
        ValueError,
        match="side-effect approval input binding failed: ability dependencies not complete",
    ):
        coordinator.approve_review_and_queue(
            tenant_id=tenant_id,
            task_id=task.id,
            actor="admin:user-123",
            approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    assert task.status == ExecutionTaskState.PENDING_REVIEW.value
    assert "execution_constraints" not in task.metadata_json
    coordinator._queue.enqueue_task.assert_not_called()


def test_composition_issued_grant_does_not_bypass_side_effect_review() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id)
    task.metadata_json = {
        "task_type": "tool.invoke",
        "tool_invocation": {
            "schema_version": 1,
            "action": "gtm.email_send",
            "input": {"to": "lead@example.com"},
        },
        "execution_constraints": {
            "side_effect_authorization": {
                "schema_version": 1,
                "allowed_actions": ["gtm.email_send"],
                "reason": "compiled",
                "approved_by": "mission_composition_engine",
            }
        },
    }
    queue = MagicMock()
    coordinator = _coordinator_with_task(task=task, queue=queue)

    result = coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    assert result.state == ExecutionTaskState.PENDING_REVIEW.value
    queue.enqueue_task.assert_not_called()


def test_approve_review_rejects_already_queued_task_without_enqueueing() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.QUEUED.value)
    queue = MagicMock()
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="expected status 'pending_review', got 'queued'"):
        coordinator.approve_review_and_queue(tenant_id=tenant_id, task_id=task.id, actor="admin-test")

    coordinator._tasks.get_for_update.assert_called_once_with(task.id)
    queue.enqueue_task.assert_not_called()
    coordinator._governance.append.assert_not_called()
    coordinator._audit.append.assert_not_called()


def test_mark_dead_letter_restores_previous_state_when_queue_move_fails() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.FAILED.value)
    queue = MagicMock()
    queue.move_to_dead_letter.return_value = QueueOperationResult(ok=False, reason="redis dead-letter unavailable")
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="redis dead-letter unavailable"):
        coordinator.mark_dead_letter(
            tenant_id=tenant_id,
            task_id=task.id,
            reason="retry budget exhausted",
        )

    assert task.status == ExecutionTaskState.FAILED.value
    coordinator._governance.append.assert_not_called()


def test_mark_dead_letter_moves_task_to_dead_letter_and_emits_governance_evidence() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.FAILED.value)
    queue = MagicMock()
    queue.move_to_dead_letter.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    result = coordinator.mark_dead_letter(
        tenant_id=tenant_id,
        task_id=task.id,
        reason="retry budget exhausted",
    )

    assert result.ok is True
    assert result.task_id == task.id
    assert result.state == ExecutionTaskState.DEAD_LETTERED.value
    assert task.status == ExecutionTaskState.DEAD_LETTERED.value
    queue.move_to_dead_letter.assert_called_once_with(
        tenant_id=tenant_id,
        task_id=task.id,
        reason="retry budget exhausted",
    )

    coordinator._governance.append.assert_called_once()
    governance_event = coordinator._governance.append.call_args.args[0]
    assert governance_event.tenant_id == tenant_id
    assert governance_event.mission_id == task.mission_id
    assert governance_event.event_type == "dead_letter"
    assert governance_event.actor == "execution_coordinator"
    assert governance_event.decision == "retry budget exhausted"
    assert governance_event.payload_json == {"task_id": str(task.id)}
    assert coordinator._session.flush.call_count == 2


def test_retry_task_reenters_admission_and_canonical_queue_boundary() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.FAILED.value)
    queue = MagicMock()
    queue.list_dead_letter.return_value = []
    queue.recover_task_for_retry.return_value = QueueOperationResult(
        ok=False,
        reason="task not found in processing or pending queue",
    )
    queue.enqueue_task.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    result = coordinator.retry_task(tenant_id=tenant_id, task_id=task.id)

    assert result.ok is True
    assert task.status == ExecutionTaskState.QUEUED.value
    coordinator._governor.evaluate.assert_called_once()
    coordinator._policy.evaluate_task.assert_called_once_with(task)
    queue.enqueue_task.assert_called_once()


def test_retry_side_effect_without_current_grant_returns_to_review() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.DEAD_LETTERED.value)
    task.metadata_json = {
        "task_type": "tool.invoke",
        "tool_invocation": {
            "schema_version": 1,
            "action": "gtm.email_send",
            "input": {"to": "lead@example.com"},
        },
    }
    queue = MagicMock()
    coordinator = _coordinator_with_task(task=task, queue=queue)

    result = coordinator.retry_task(tenant_id=tenant_id, task_id=task.id)

    assert result.ok is False
    assert result.state == ExecutionTaskState.PENDING_REVIEW.value
    assert "current independent human approval" in str(result.reason)
    queue.enqueue_task.assert_not_called()
    queue.retry_dead_letter.assert_not_called()


def test_queue_task_rejects_duplicate_already_queued_task_without_enqueuing() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.QUEUED.value)
    queue = MagicMock()
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="Invalid task transition"):
        coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    queue.enqueue_task.assert_not_called()
    coordinator._audit.append.assert_not_called()


def test_queue_task_rejects_terminal_completed_task() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.COMPLETED.value)
    queue = MagicMock()
    coordinator = _coordinator_with_task(task=task, queue=queue)

    with pytest.raises(ValueError, match="Invalid task transition"):
        coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)

    queue.enqueue_task.assert_not_called()


def test_social_publication_moves_from_draft_to_reviewed_to_authorized() -> None:
    tenant_id = str(uuid.uuid4())
    task = _task(tenant_id=tenant_id, status=ExecutionTaskState.PLANNED.value)
    task.metadata_json = {
        "task_type": "tool.invoke",
        "social_publication_state": "draft",
        "tool_invocation": {
            "schema_version": 1,
            "action": "gtm.social_publish",
            "input": {"platform": "x", "content": "Draft"},
        },
    }
    queue = MagicMock()
    queue.enqueue_task.return_value = QueueOperationResult(ok=True)
    coordinator = _coordinator_with_task(task=task, queue=queue)

    review = coordinator.queue_task(tenant_id=tenant_id, task_id=task.id)
    assert review.ok is False
    assert task.metadata_json["social_publication_state"] == "reviewed"

    coordinator._tasks.get_for_update.return_value = task
    approved = coordinator.approve_review_and_queue(
        tenant_id=tenant_id,
        task_id=task.id,
        actor="admin:user-123",
        approval_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    assert approved.ok is True
    assert task.metadata_json["social_publication_state"] == "authorized"
