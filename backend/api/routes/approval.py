"""
Approval workflow API endpoints.

Provides REST API for managing approval requests:
- POST /api/v1/approval/requests - Create approval request
- GET /api/v1/approval/requests - List approval requests
- GET /api/v1/approval/requests/{request_id} - Get approval request
- POST /api/v1/approval/requests/{request_id}/approve - Approve request
- POST /api/v1/approval/requests/{request_id}/reject - Reject request
- DELETE /api/v1/approval/requests/{request_id} - Cancel request
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

from backend.agents.compliance.approval import (
    ApprovalStatus,
    get_approval_store,
)

router = APIRouter(prefix="/api/v1/approval", tags=["approval"])


# Request/Response Models


class CreateApprovalRequest(BaseModel):
    """Request to create approval"""

    agent_id: str = Field(..., description="ID of agent requesting approval")
    agent_type: str = Field(..., description="Type of agent")
    tool_name: str = Field(..., description="Tool requiring approval")
    parameters: Dict[str, Any] = Field(..., description="Tool parameters")
    reason: str = Field(..., description="Reason for requiring approval")
    expires_in_seconds: Optional[int] = Field(None, description="Expiration time in seconds")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class ApprovalResponse(BaseModel):
    """Approval request response"""

    id: str
    agent_id: str
    agent_type: str
    tool_name: str
    parameters: Dict[str, Any]
    reason: str
    requested_at: str
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    approval_note: Optional[str] = None
    expires_at: Optional[str] = None
    metadata: Dict[str, Any]


class ApproveRequest(BaseModel):
    """Request to approve"""

    approved_by: str = Field(..., description="User approving the request")
    note: Optional[str] = Field(None, description="Optional approval note")


class RejectRequest(BaseModel):
    """Request to reject"""

    rejected_by: str = Field(..., description="User rejecting the request")
    note: Optional[str] = Field(None, description="Optional rejection note")


class ApprovalListResponse(BaseModel):
    """List of approval requests"""

    requests: List[ApprovalResponse]
    total: int


# API Endpoints


@router.post("/requests", response_model=ApprovalResponse, status_code=201)
async def create_approval_request(request: CreateApprovalRequest):
    """
    Create new approval request.

    Args:
        request: Approval request data

    Returns:
        Created approval request
    """
    store = get_approval_store()

    approval_request = store.create(
        agent_id=request.agent_id,
        agent_type=request.agent_type,
        tool_name=request.tool_name,
        parameters=request.parameters,
        reason=request.reason,
        expires_in_seconds=request.expires_in_seconds,
        metadata=request.metadata,
    )

    return ApprovalResponse(**approval_request.to_dict())


@router.get("/requests", response_model=ApprovalListResponse)
async def list_approval_requests(
    status: Optional[str] = Query(None, description="Filter by status"),
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of requests"),
):
    """
    List approval requests.

    Args:
        status: Optional status filter
        agent_id: Optional agent ID filter
        limit: Maximum number of requests

    Returns:
        List of approval requests
    """
    store = get_approval_store()

    # Cleanup expired requests
    store.cleanup_expired()

    # Parse status
    status_enum = None
    if status:
        try:
            status_enum = ApprovalStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Valid values: {[s.value for s in ApprovalStatus]}",  # noqa: E501
            )

    requests = store.list(status=status_enum, agent_id=agent_id, limit=limit)

    return ApprovalListResponse(
        requests=[ApprovalResponse(**r.to_dict()) for r in requests],
        total=len(requests),
    )


@router.get("/requests/{request_id}", response_model=ApprovalResponse)
async def get_approval_request(request_id: str):
    """
    Get approval request by ID.

    Args:
        request_id: Request ID

    Returns:
        Approval request
    """
    store = get_approval_store()
    request = store.get(request_id)

    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")

    # Check if expired
    if request.is_expired() and request.status == ApprovalStatus.PENDING:
        request.status = ApprovalStatus.EXPIRED
        store.update(request)

    return ApprovalResponse(**request.to_dict())


@router.post("/requests/{request_id}/approve", response_model=ApprovalResponse)
async def approve_request(request_id: str, approve_req: ApproveRequest):
    """
    Approve approval request.

    Args:
        request_id: Request ID
        approve_req: Approval data

    Returns:
        Updated approval request
    """
    store = get_approval_store()
    request = store.get(request_id)

    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if not request.is_pending():
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve request with status: {request.status.value}",
        )

    if request.is_expired():
        request.status = ApprovalStatus.EXPIRED
        store.update(request)
        raise HTTPException(status_code=400, detail="Approval request has expired")

    request.approve(approved_by=approve_req.approved_by, note=approve_req.note)
    store.update(request)

    return ApprovalResponse(**request.to_dict())


@router.post("/requests/{request_id}/reject", response_model=ApprovalResponse)
async def reject_request(request_id: str, reject_req: RejectRequest):
    """
    Reject approval request.

    Args:
        request_id: Request ID
        reject_req: Rejection data

    Returns:
        Updated approval request
    """
    store = get_approval_store()
    request = store.get(request_id)

    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if not request.is_pending():
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject request with status: {request.status.value}",
        )

    request.reject(rejected_by=reject_req.rejected_by, note=reject_req.note)
    store.update(request)

    return ApprovalResponse(**request.to_dict())


@router.delete("/requests/{request_id}", status_code=204)
async def cancel_request(request_id: str):
    """
    Cancel approval request.

    Args:
        request_id: Request ID

    Returns:
        No content
    """
    store = get_approval_store()
    request = store.get(request_id)

    if not request:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if not request.is_pending():
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel request with status: {request.status.value}",
        )

    request.cancel()
    store.update(request)

    return None


@router.post("/requests/cleanup", status_code=200)
async def cleanup_expired_requests():
    """
    Cleanup expired approval requests.

    Returns:
        Number of requests marked as expired
    """
    store = get_approval_store()
    count = store.cleanup_expired()

    return {"expired_count": count}
