from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.api.routes._authorization import require_route_permission
from backend.app.dependencies.db import get_request_tenant_id, get_tenant_db_session
from backend.app.dependencies.services import get_queue_adapter
from backend.auth.permissions import Permission
from backend.queue.base import QueueAdapter
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.services.document_artifacts import list_review_queue, read_artifact, update_review_status
from backend.services.execution_coordinator import ExecutionCoordinator

router = APIRouter(prefix="/review-queue", tags=["review-queue"])

ReviewStatus = Literal["pending", "approved", "rejected", "sent"]


class ReviewQueueItem(BaseModel):
    artifact_id: str
    artifact_type: str
    review_status: str
    content: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    mission_id: str | None = None
    task_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ReviewQueueListResponse(BaseModel):
    items: list[ReviewQueueItem]
    total: int


class PendingTaskReviewItem(BaseModel):
    task_id: str
    mission_id: str
    artifact_type: str
    review_status: str
    content: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class PendingTaskReviewListResponse(BaseModel):
    items: list[PendingTaskReviewItem]
    total: int


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=2000)


class TaskApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_expires_at: datetime


class TaskApprovalResponse(BaseModel):
    task_id: str
    previous_status: str
    status: str


class TaskApprovalRevocationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


def _to_item(row: dict[str, Any], *, artifact_id: str, default_status: str) -> ReviewQueueItem:
    return ReviewQueueItem(
        artifact_id=str(row.get("artifact_id") or row.get("id") or artifact_id),
        artifact_type=str(row.get("artifact_type") or ""),
        review_status=str(row.get("review_status") or default_status),
        content=dict(row.get("content") or {}),
        metadata=dict(row.get("metadata") or {}),
        mission_id=row.get("mission_id"),
        task_id=row.get("task_id"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


@router.get("", response_model=ReviewQueueListResponse)
def list_queue(
    request: Request,
    status: ReviewStatus = Query(default="pending"),
    limit: int = Query(default=20, ge=1, le=50),
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> ReviewQueueListResponse:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    rows = list_review_queue(session, tenant_id=str(tenant_id), status=status, limit=limit)
    items = [_to_item(row, artifact_id="", default_status=status) for row in rows]
    return ReviewQueueListResponse(items=items, total=len(items))


@router.get("/tasks", response_model=PendingTaskReviewListResponse)
def list_pending_tasks(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> PendingTaskReviewListResponse:
    """Expose approval-gated execution tasks alongside document artifacts."""
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    tasks = ExecutionTaskRepository(session).list_pending_review_for_tenant(
        tenant_id=str(tenant_id), limit=limit
    )
    items = [
        PendingTaskReviewItem(
            task_id=str(task.id),
            mission_id=str(task.mission_id),
            artifact_type="execution_task",
            review_status="pending_review",
            content={"title": task.title, "description": task.description},
            metadata={
                "action": (task.metadata_json or {}).get("tool_invocation", {}).get("action"),
                "approval_reason": (task.metadata_json or {}).get("approval_reason"),
                "requires_human_review": task.requires_human_review,
            },
            created_at=task.created_at.isoformat() if task.created_at else None,
        )
        for task in tasks
    ]
    return PendingTaskReviewListResponse(items=items, total=len(items))


@router.get("/{artifact_id}", response_model=ReviewQueueItem)
def get_queue_item(
    artifact_id: str,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> ReviewQueueItem:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.EXECUTION_VIEW,
        tenant_id=tenant_id,
    )
    row = read_artifact(session, tenant_id=str(tenant_id), artifact_id=artifact_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="artifact not found")
    return _to_item(row, artifact_id=artifact_id, default_status="pending")


@router.post("/{artifact_id}/approve", response_model=ReviewQueueItem)
def approve_queue_item(
    artifact_id: str,
    body: ReviewDecisionRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> ReviewQueueItem:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.OUTCOME_REVIEW_MANAGE,
        tenant_id=tenant_id,
    )
    try:
        existing = read_artifact(session, tenant_id=str(tenant_id), artifact_id=artifact_id)
        row = update_review_status(
            session,
            tenant_id=str(tenant_id),
            artifact_id=artifact_id,
            review_status="approved",
            actor="operator",
            note=body.note,
        )
        from backend.services.light_crm.workflow import on_draft_approved

        content = dict(existing.get("content") or {}) if isinstance(existing, dict) else {}
        on_draft_approved(
            session=session,
            tenant_id=str(tenant_id),
            artifact_id=artifact_id,
            artifact_content=content,
            note=body.note,
        )
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_item(row, artifact_id=artifact_id, default_status="approved")


@router.post("/{artifact_id}/reject", response_model=ReviewQueueItem)
def reject_queue_item(
    artifact_id: str,
    body: ReviewDecisionRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
) -> ReviewQueueItem:
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.OUTCOME_REVIEW_MANAGE,
        tenant_id=tenant_id,
    )
    try:
        row = update_review_status(
            session,
            tenant_id=str(tenant_id),
            artifact_id=artifact_id,
            review_status="rejected",
            actor="operator",
            note=body.note,
        )
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_item(row, artifact_id=artifact_id, default_status="rejected")


@router.post("/tasks/{task_id}/approve", response_model=TaskApprovalResponse)
def approve_tenant_task(
    task_id: uuid.UUID,
    body: TaskApprovalRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> TaskApprovalResponse:
    """Issue a tenant-scoped, payload-bound approval and queue the reviewed task."""
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.OUTCOME_REVIEW_MANAGE,
        tenant_id=tenant_id,
    )
    task = ExecutionTaskRepository(session).get_for_tenant(task_id=task_id, tenant_id=str(tenant_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    previous_status = task.status
    principal = getattr(request.state, "principal", None)
    actor = str(getattr(principal, "subject_id", "") or "")
    if not actor:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="authenticated reviewer required")
    try:
        result = ExecutionCoordinator(session, queue).approve_review_and_queue(
            tenant_id=str(tenant_id),
            task_id=task_id,
            actor=actor,
            approval_expires_at=body.approval_expires_at,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TaskApprovalResponse(
        task_id=str(task_id),
        previous_status=previous_status,
        status=result.state,
    )


@router.post("/tasks/{task_id}/revoke", response_model=TaskApprovalResponse)
def revoke_tenant_task_approval(
    task_id: uuid.UUID,
    body: TaskApprovalRevocationRequest,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_request_tenant_id),
    session: Session = Depends(get_tenant_db_session),
    queue: QueueAdapter = Depends(get_queue_adapter),
) -> TaskApprovalResponse:
    """Revoke an unconsumed task approval; runtime will reject the queued effect."""
    require_route_permission(
        request=request,
        db=session,
        permission=Permission.OUTCOME_REVIEW_MANAGE,
        tenant_id=tenant_id,
    )
    task = ExecutionTaskRepository(session).get_for_tenant(task_id=task_id, tenant_id=str(tenant_id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    previous_status = task.status
    principal = getattr(request.state, "principal", None)
    actor = str(getattr(principal, "subject_id", "") or "")
    if not actor:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="authenticated reviewer required")
    try:
        result = ExecutionCoordinator(session, queue).revoke_side_effect_approval(
            tenant_id=str(tenant_id),
            task_id=task_id,
            actor=actor,
            reason=body.reason,
        )
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TaskApprovalResponse(
        task_id=str(task_id),
        previous_status=previous_status,
        status=result.state,
    )
