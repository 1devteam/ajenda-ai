"""
Approval workflow system for Omnipath V2 compliance.

Manages approval requests for sensitive operations, tracks approval status,
and integrates with compliance engine.
"""

from enum import Enum
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import uuid


class ApprovalStatus(str, Enum):
    """Approval request status"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class ApprovalRequest:
    """
    Approval request for a sensitive operation.
    
    Attributes:
        id: Unique request ID
        agent_id: ID of agent requesting approval
        agent_type: Type of agent
        tool_name: Tool requiring approval
        parameters: Tool parameters
        reason: Reason for requiring approval
        requested_at: When approval was requested
        status: Current approval status
        approved_by: User who approved/rejected
        approved_at: When approval was granted/rejected
        approval_note: Note from approver
        expires_at: When request expires
        metadata: Additional metadata
    """
    id: str
    agent_id: str
    agent_type: str
    tool_name: str
    parameters: Dict[str, Any]
    reason: str
    requested_at: datetime
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_note: Optional[str] = None
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_pending(self) -> bool:
        """Check if request is pending"""
        return self.status == ApprovalStatus.PENDING
    
    def is_approved(self) -> bool:
        """Check if request is approved"""
        return self.status == ApprovalStatus.APPROVED
    
    def is_rejected(self) -> bool:
        """Check if request is rejected"""
        return self.status == ApprovalStatus.REJECTED
    
    def is_expired(self) -> bool:
        """Check if request is expired"""
        if self.status == ApprovalStatus.EXPIRED:
            return True
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return True
        return False
    
    def approve(self, approved_by: str, note: Optional[str] = None) -> None:
        """
        Approve the request.
        
        Args:
            approved_by: User approving the request
            note: Optional approval note
        """
        self.status = ApprovalStatus.APPROVED
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.approval_note = note
    
    def reject(self, rejected_by: str, note: Optional[str] = None) -> None:
        """
        Reject the request.
        
        Args:
            rejected_by: User rejecting the request
            note: Optional rejection note
        """
        self.status = ApprovalStatus.REJECTED
        self.approved_by = rejected_by
        self.approved_at = datetime.utcnow()
        self.approval_note = note
    
    def cancel(self) -> None:
        """Cancel the request"""
        self.status = ApprovalStatus.CANCELLED
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "reason": self.reason,
            "requested_at": self.requested_at.isoformat(),
            "status": self.status.value,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approval_note": self.approval_note,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
        }


class ApprovalStore:
    """
    In-memory store for approval requests.
    
    For production, replace with database (PostgreSQL, Redis, etc.)
    """
    
    def __init__(self):
        """Initialize approval store"""
        self._requests: Dict[str, ApprovalRequest] = {}
    
    def create(
        self,
        agent_id: str,
        agent_type: str,
        tool_name: str,
        parameters: Dict[str, Any],
        reason: str,
        expires_in_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ApprovalRequest:
        """
        Create new approval request.
        
        Args:
            agent_id: ID of agent requesting approval
            agent_type: Type of agent
            tool_name: Tool requiring approval
            parameters: Tool parameters
            reason: Reason for requiring approval
            expires_in_seconds: Optional expiration time in seconds
            metadata: Optional metadata
        
        Returns:
            ApprovalRequest instance
        """
        request_id = str(uuid.uuid4())
        requested_at = datetime.utcnow()
        expires_at = None
        
        if expires_in_seconds:
            from datetime import timedelta
            expires_at = requested_at + timedelta(seconds=expires_in_seconds)
        
        request = ApprovalRequest(
            id=request_id,
            agent_id=agent_id,
            agent_type=agent_type,
            tool_name=tool_name,
            parameters=parameters,
            reason=reason,
            requested_at=requested_at,
            expires_at=expires_at,
            metadata=metadata or {}
        )
        
        self._requests[request_id] = request
        return request
    
    def get(self, request_id: str) -> Optional[ApprovalRequest]:
        """
        Get approval request by ID.
        
        Args:
            request_id: Request ID
        
        Returns:
            ApprovalRequest or None if not found
        """
        return self._requests.get(request_id)
    
    def list(
        self,
        status: Optional[ApprovalStatus] = None,
        agent_id: Optional[str] = None,
        limit: int = 100
    ) -> List[ApprovalRequest]:
        """
        List approval requests.
        
        Args:
            status: Optional status filter
            agent_id: Optional agent ID filter
            limit: Maximum number of requests to return
        
        Returns:
            List of ApprovalRequest instances
        """
        requests = list(self._requests.values())
        
        # Filter by status
        if status:
            requests = [r for r in requests if r.status == status]
        
        # Filter by agent_id
        if agent_id:
            requests = [r for r in requests if r.agent_id == agent_id]
        
        # Sort by requested_at (newest first)
        requests.sort(key=lambda r: r.requested_at, reverse=True)
        
        return requests[:limit]
    
    def update(self, request: ApprovalRequest) -> None:
        """
        Update approval request.
        
        Args:
            request: ApprovalRequest instance
        """
        self._requests[request.id] = request
    
    def delete(self, request_id: str) -> bool:
        """
        Delete approval request.
        
        Args:
            request_id: Request ID
        
        Returns:
            True if deleted, False if not found
        """
        if request_id in self._requests:
            del self._requests[request_id]
            return True
        return False
    
    def cleanup_expired(self) -> int:
        """
        Mark expired requests as expired.
        
        Returns:
            Number of requests marked as expired
        """
        count = 0
        now = datetime.utcnow()
        
        for request in self._requests.values():
            if request.status == ApprovalStatus.PENDING:
                if request.expires_at and now > request.expires_at:
                    request.status = ApprovalStatus.EXPIRED
                    count += 1
        
        return count


# Global approval store instance
_global_approval_store: Optional[ApprovalStore] = None


def get_approval_store() -> ApprovalStore:
    """
    Get global approval store instance.
    
    Returns:
        ApprovalStore instance
    """
    global _global_approval_store
    if _global_approval_store is None:
        _global_approval_store = ApprovalStore()
    return _global_approval_store


def set_approval_store(store: ApprovalStore) -> None:
    """
    Set global approval store instance.
    
    Args:
        store: ApprovalStore instance
    """
    global _global_approval_store
    _global_approval_store = store
