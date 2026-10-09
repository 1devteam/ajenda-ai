"""Approval-state projection for the RevOps mission deliverable."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import ValidationError

from backend.domain.enums import ExecutionTaskState
from backend.domain.execution_task import ExecutionTask
from backend.domain.outcome_review import OutcomeReview
from backend.services.mission_composition.revops_deliverable_contracts import (
    RevOpsApprovalStateRead,
    RevOpsDraftApprovalRead,
    RevOpsOutcomeReviewRead,
    RevOpsProspectRead,
    RevOpsTaskApprovalRead,
)
from backend.services.mission_composition.revops_deliverable_prospects import _task_action
from backend.services.tools.schemas import SideEffectAuthorization, SideEffectAuthorizationV2


def _task_approval(
    task: ExecutionTask,
    *,
    now: datetime,
) -> RevOpsTaskApprovalRead | None:
    metadata = task.metadata_json if isinstance(task.metadata_json, dict) else {}
    constraints = metadata.get("execution_constraints")
    raw_grant = constraints.get("side_effect_authorization") if isinstance(constraints, dict) else None
    relevant = (
        task.requires_human_review or task.status == ExecutionTaskState.PENDING_REVIEW.value or raw_grant is not None
    )
    if not relevant:
        return None

    action = _task_action(task)
    if raw_grant is None:
        return RevOpsTaskApprovalRead(
            task_id=task.id,
            action=action,
            task_status=task.status,
            status="pending",
        )
    if not isinstance(raw_grant, dict):
        return RevOpsTaskApprovalRead(
            task_id=task.id,
            action=action,
            task_status=task.status,
            status="invalid",
        )

    if raw_grant.get("schema_version") == 2:
        try:
            grant = SideEffectAuthorizationV2.model_validate(raw_grant)
        except ValidationError:
            return RevOpsTaskApprovalRead(
                task_id=task.id,
                action=action,
                task_status=task.status,
                status="invalid",
            )
        approval_status: Literal["approved", "consumed", "expired", "revoked"]
        if grant.revoked_at is not None:
            approval_status = "revoked"
        elif task.status == ExecutionTaskState.COMPLETED.value:
            approval_status = "consumed"
        elif now >= grant.expires_at.astimezone(UTC):
            approval_status = "expired"
        else:
            approval_status = "approved"
        return RevOpsTaskApprovalRead(
            task_id=task.id,
            action=action,
            task_status=task.status,
            status=approval_status,
            grant_id=grant.grant_id,
            approved_by=grant.approved_by,
            expires_at=grant.expires_at,
        )

    try:
        legacy = SideEffectAuthorization.model_validate(raw_grant)
    except ValidationError:
        return RevOpsTaskApprovalRead(
            task_id=task.id,
            action=action,
            task_status=task.status,
            status="invalid",
        )
    return RevOpsTaskApprovalRead(
        task_id=task.id,
        action=action,
        task_status=task.status,
        status="consumed" if task.status == ExecutionTaskState.COMPLETED.value else "approved",
        approved_by=legacy.approved_by,
    )


def _approval_state(
    *,
    prospects: Sequence[RevOpsProspectRead],
    tasks: Sequence[ExecutionTask],
    outcome_reviews: Sequence[OutcomeReview],
    now: datetime,
) -> RevOpsApprovalStateRead:
    draft_approvals = tuple(
        RevOpsDraftApprovalRead(artifact_id=draft.artifact_id, status=draft.review_status)
        for prospect in prospects
        for draft in prospect.drafts
    )
    task_approvals = tuple(
        approval
        for task in sorted(tasks, key=lambda item: str(item.id))
        if (approval := _task_approval(task, now=now)) is not None
    )
    reviews = tuple(
        RevOpsOutcomeReviewRead(
            review_id=review.id,
            review_status=review.review_status,
            review_decision=review.review_decision,
            human_approval_required=review.human_approval_required,
            human_approval_status=review.human_approval_status,
        )
        for review in sorted(outcome_reviews, key=lambda item: (item.created_at, str(item.id)))
    )
    draft_ready = all(item.status in {"approved", "sent"} for item in draft_approvals)
    task_ready = all(item.status in {"approved", "consumed"} for item in task_approvals)
    review_ready = all(
        not item.human_approval_required or item.human_approval_status in {"approved", "not_required"}
        for item in reviews
    )
    return RevOpsApprovalStateRead(
        draft_approvals=draft_approvals,
        task_approvals=task_approvals,
        outcome_reviews=reviews,
        all_required_approved=draft_ready and task_ready and review_ready,
    )
