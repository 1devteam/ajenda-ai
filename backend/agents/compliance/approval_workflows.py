"""
Tiered Approval Workflows for Omnipath V2.

This module implements risk-based approval workflows with:
1. Approval request creation and routing
2. State management (pending, approved, rejected, escalated, expired, executed)
3. Authority-based approval matrix
4. Timeout handling
5. Audit trail

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import uuid

from .risk_scoring import RiskTier, get_risk_scoring_engine
from .regulatory_mapping import AuthorityLevel
from ..registry.asset_registry import get_registry
from ..registry.lineage_tracker import get_tracker


class ApprovalState(str, Enum):
    """States for approval requests."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    EXECUTED = "executed"


@dataclass
class ApprovalRequest:
    """
    Approval request for a high-risk operation.

    Attributes:
        request_id: Unique request identifier
        asset_id: AIAsset being accessed/modified
        operation: Operation being performed
        requester_id: User requesting approval
        risk_tier: Risk tier of the asset
        risk_score: Calculated risk score
        state: Current state of request
        created_at: When request was created
        required_approver_level: Minimum authority level required
        approver_id: Who approved/rejected
        approved_at: When approved/rejected
        rejection_reason: Reason for rejection
        escalation_reason: Reason for escalation
        justification: Requester's justification
        notes: Additional notes
        expires_at: When request expires
    """

    request_id: str
    asset_id: str
    operation: str
    requester_id: str
    risk_tier: RiskTier
    risk_score: float
    state: ApprovalState
    created_at: datetime
    required_approver_level: AuthorityLevel
    approver_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    escalation_reason: Optional[str] = None
    justification: Optional[str] = None
    notes: Optional[str] = None
    expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "request_id": self.request_id,
            "asset_id": self.asset_id,
            "operation": self.operation,
            "requester_id": self.requester_id,
            "risk_tier": self.risk_tier.value,
            "risk_score": self.risk_score,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "required_approver_level": self.required_approver_level.value,
            "approver_id": self.approver_id,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejection_reason": self.rejection_reason,
            "escalation_reason": self.escalation_reason,
            "justification": self.justification,
            "notes": self.notes,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    def is_expired(self) -> bool:
        """Check if request has expired."""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at


@dataclass
class ApprovalPolicy:
    """
    Configurable approval policy.

    Attributes:
        auto_approve_minimal: Auto-approve minimal risk
        timeout_hours_critical: Timeout for critical risk (hours)
        timeout_hours_high: Timeout for high risk (hours)
        timeout_hours_medium: Timeout for medium risk (hours)
        timeout_hours_low: Timeout for low risk (hours)
        auto_approve_on_timeout: Auto-approve on timeout for medium/low
    """

    auto_approve_minimal: bool = True
    timeout_hours_critical: int = 24
    timeout_hours_high: int = 24
    timeout_hours_medium: int = 72
    timeout_hours_low: int = 72
    auto_approve_on_timeout: bool = False  # Conservative default


class ApprovalWorkflow:
    """
    Singleton managing approval request lifecycle.

    This class handles:
    - Creating approval requests based on risk tier
    - Routing to appropriate approvers
    - Processing approvals/rejections/escalations
    - Timeout handling
    - Audit trail via lineage tracker

    Approval Matrix:
        Minimal: Auto-approved (if policy allows)
        Low: Operator (AuthorityLevel.OPERATOR)
        Medium: Admin (AuthorityLevel.ADMIN)
        High: Compliance Officer (AuthorityLevel.COMPLIANCE_OFFICER)
        Critical: C-Level (custom level 5+, or Compliance Officer with notes)

    Example:
        workflow = get_approval_workflow()

        # Check if approval required
        required, tier = workflow.check_approval_required("asset-001", "execute")

        if required:
            # Create approval request
            request = workflow.create_approval_request(
                asset_id="asset-001",
                operation="execute",
                requester_id="user-001",
                justification="Need to run medical diagnosis"
            )

            # Approve
            workflow.approve_request(
                request_id=request.request_id,
                approver_id="compliance-officer-001",
                notes="Approved with oversight"
            )
    """

    _instance: Optional["ApprovalWorkflow"] = None

    # Approval matrix: risk tier -> required authority level
    APPROVAL_MATRIX = {
        RiskTier.MINIMAL: None,  # Auto-approved
        RiskTier.LOW: AuthorityLevel.OPERATOR,
        RiskTier.MEDIUM: AuthorityLevel.ADMIN,
        RiskTier.HIGH: AuthorityLevel.COMPLIANCE_OFFICER,
        RiskTier.CRITICAL: AuthorityLevel.COMPLIANCE_OFFICER,  # With special notes
    }

    def __new__(cls):
        """Ensure singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize approval workflow."""
        self.registry = get_registry()
        self.risk_engine = get_risk_scoring_engine()
        self.lineage_tracker = get_tracker()
        self.policy = ApprovalPolicy()

        # In-memory storage for approval requests
        # In production, this would be a database
        self._requests: Dict[str, ApprovalRequest] = {}

    def create_approval_request(
        self,
        asset_id: str,
        operation: str,
        requester_id: str,
        justification: Optional[str] = None,
    ) -> ApprovalRequest:
        """
        Create an approval request for an operation.

        Args:
            asset_id: AIAsset identifier
            operation: Operation being performed
            requester_id: User requesting approval
            justification: Optional justification

        Returns:
            ApprovalRequest

        Raises:
            ValueError: If asset not found or risk not calculated
        """
        # Get asset
        asset = self.registry.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        # Get risk score
        risk_score = self.risk_engine.get_score(asset_id)
        if not risk_score:
            raise ValueError(f"Risk score not calculated for {asset_id}")

        # Determine required approver level
        required_level = self.APPROVAL_MATRIX.get(risk_score.tier)

        # Calculate expiration
        expires_at = self._calculate_expiration(risk_score.tier)

        # Create request
        request = ApprovalRequest(
            request_id=str(uuid.uuid4()),
            asset_id=asset_id,
            operation=operation,
            requester_id=requester_id,
            risk_tier=risk_score.tier,
            risk_score=risk_score.score,
            state=ApprovalState.PENDING,
            created_at=datetime.utcnow(),
            required_approver_level=required_level,
            justification=justification,
            expires_at=expires_at,
        )

        # Store request
        self._requests[request.request_id] = request

        # Track in lineage
        self.lineage_tracker.track_event(
            asset_id=asset_id,
            event_type="approval_request_created",
            description=f"Approval request created for {operation}",
            metadata={
                "request_id": request.request_id,
                "operation": operation,
                "requester_id": requester_id,
                "risk_tier": risk_score.tier.value,
                "risk_score": risk_score.score,
            },
        )

        return request

    def _calculate_expiration(self, risk_tier: RiskTier) -> datetime:
        """Calculate expiration time based on risk tier."""
        hours_map = {
            RiskTier.CRITICAL: self.policy.timeout_hours_critical,
            RiskTier.HIGH: self.policy.timeout_hours_high,
            RiskTier.MEDIUM: self.policy.timeout_hours_medium,
            RiskTier.LOW: self.policy.timeout_hours_low,
            RiskTier.MINIMAL: 1,  # Should be auto-approved
        }

        hours = hours_map.get(risk_tier, 24)
        return datetime.utcnow() + timedelta(hours=hours)

    def approve_request(
        self,
        request_id: str,
        approver_id: str,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Approve an approval request.

        Args:
            request_id: Request identifier
            approver_id: User approving
            notes: Optional notes

        Returns:
            True if approved, False otherwise

        Raises:
            ValueError: If request not found or invalid state
        """
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Approval request {request_id} not found")

        # Check state
        if request.state != ApprovalState.PENDING:
            raise ValueError(f"Request is not pending (state: {request.state})")

        # Check if expired
        if request.is_expired():
            request.state = ApprovalState.EXPIRED
            return False

        # Update request
        request.state = ApprovalState.APPROVED
        request.approver_id = approver_id
        request.approved_at = datetime.utcnow()
        request.notes = notes

        # Track in lineage
        self.lineage_tracker.track_event(
            asset_id=request.asset_id,
            event_type="approval_granted",
            description=f"Approval granted for {request.operation}",
            metadata={
                "request_id": request_id,
                "approver_id": approver_id,
                "notes": notes,
            },
        )

        return True

    def reject_request(
        self,
        request_id: str,
        approver_id: str,
        reason: str,
    ) -> bool:
        """
        Reject an approval request.

        Args:
            request_id: Request identifier
            approver_id: User rejecting
            reason: Rejection reason

        Returns:
            True if rejected, False otherwise

        Raises:
            ValueError: If request not found or invalid state
        """
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Approval request {request_id} not found")

        # Check state
        if request.state != ApprovalState.PENDING:
            raise ValueError(f"Request is not pending (state: {request.state})")

        # Update request
        request.state = ApprovalState.REJECTED
        request.approver_id = approver_id
        request.approved_at = datetime.utcnow()
        request.rejection_reason = reason

        # Track in lineage
        self.lineage_tracker.track_event(
            asset_id=request.asset_id,
            event_type="approval_rejected",
            description=f"Approval rejected for {request.operation}",
            metadata={
                "request_id": request_id,
                "approver_id": approver_id,
                "reason": reason,
            },
        )

        return True

    def escalate_request(
        self,
        request_id: str,
        escalated_by: str,
        reason: str,
    ) -> bool:
        """
        Escalate an approval request to higher authority.

        Args:
            request_id: Request identifier
            escalated_by: User escalating
            reason: Escalation reason

        Returns:
            True if escalated, False otherwise

        Raises:
            ValueError: If request not found or invalid state
        """
        request = self._requests.get(request_id)
        if not request:
            raise ValueError(f"Approval request {request_id} not found")

        # Check state
        if request.state != ApprovalState.PENDING:
            raise ValueError(f"Request is not pending (state: {request.state})")

        # Update request
        request.state = ApprovalState.ESCALATED
        request.escalation_reason = reason
        request.notes = f"Escalated by {escalated_by}: {reason}"

        # Increase required authority level
        if request.required_approver_level == AuthorityLevel.OPERATOR:
            request.required_approver_level = AuthorityLevel.ADMIN
        elif request.required_approver_level == AuthorityLevel.ADMIN:
            request.required_approver_level = AuthorityLevel.COMPLIANCE_OFFICER

        # Reset to pending for higher authority
        request.state = ApprovalState.PENDING

        # Track in lineage
        self.lineage_tracker.track_event(
            asset_id=request.asset_id,
            event_type="approval_escalated",
            description=f"Approval escalated for {request.operation}",
            metadata={
                "request_id": request_id,
                "escalated_by": escalated_by,
                "reason": reason,
                "new_required_level": request.required_approver_level.value,
            },
        )

        return True

    def get_pending_requests(
        self,
        approver_id: Optional[str] = None,
        approver_level: Optional[AuthorityLevel] = None,
    ) -> List[ApprovalRequest]:
        """
        Get pending approval requests.

        Args:
            approver_id: Optional filter by approver
            approver_level: Optional filter by authority level

        Returns:
            List of pending requests
        """
        pending = [
            req
            for req in self._requests.values()
            if req.state == ApprovalState.PENDING and not req.is_expired()
        ]

        # Filter by authority level if provided
        if approver_level is not None:
            pending = [
                req
                for req in pending
                if req.required_approver_level.value <= approver_level.value
            ]

        return pending

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get approval request by ID."""
        return self._requests.get(request_id)

    def get_approval_history(self, asset_id: str) -> List[ApprovalRequest]:
        """Get approval history for an asset."""
        return [req for req in self._requests.values() if req.asset_id == asset_id]

    def check_approval_required(
        self,
        asset_id: str,
        operation: str,
    ) -> Tuple[bool, Optional[RiskTier]]:
        """
        Check if approval is required for an operation.

        Args:
            asset_id: AIAsset identifier
            operation: Operation being performed

        Returns:
            Tuple of (required: bool, risk_tier: Optional[RiskTier])
        """
        # Get risk score
        risk_score = self.risk_engine.get_score(asset_id)
        if not risk_score:
            # Calculate if not available
            risk_score = self.risk_engine.calculate_risk_score(asset_id)

        # Check if approval required based on tier
        if risk_score.tier == RiskTier.MINIMAL and self.policy.auto_approve_minimal:
            return False, risk_score.tier

        # All other tiers require approval
        return True, risk_score.tier

    def mark_executed(self, request_id: str) -> bool:
        """
        Mark an approved request as executed.

        Args:
            request_id: Request identifier

        Returns:
            True if marked, False otherwise
        """
        request = self._requests.get(request_id)
        if not request:
            return False

        if request.state != ApprovalState.APPROVED:
            return False

        request.state = ApprovalState.EXECUTED

        # Track in lineage
        self.lineage_tracker.track_event(
            asset_id=request.asset_id,
            event_type="approval_executed",
            description=f"Approved operation executed: {request.operation}",
            metadata={
                "request_id": request_id,
            },
        )

        return True

    def process_expired_requests(self) -> List[ApprovalRequest]:
        """
        Process expired requests based on policy.

        Returns:
            List of processed requests
        """
        processed = []

        for request in self._requests.values():
            if request.state != ApprovalState.PENDING:
                continue

            if not request.is_expired():
                continue

            # Handle based on risk tier and policy
            if request.risk_tier in [RiskTier.CRITICAL, RiskTier.HIGH]:
                # Block critical/high risk on timeout
                request.state = ApprovalState.EXPIRED
                request.rejection_reason = "Request expired without approval"
            elif self.policy.auto_approve_on_timeout:
                # Auto-approve medium/low on timeout if policy allows
                request.state = ApprovalState.APPROVED
                request.approver_id = "system"
                request.approved_at = datetime.utcnow()
                request.notes = "Auto-approved on timeout per policy"
            else:
                # Block on timeout
                request.state = ApprovalState.EXPIRED
                request.rejection_reason = "Request expired without approval"

            # Track in lineage
            self.lineage_tracker.track_event(
                asset_id=request.asset_id,
                event_type="approval_expired",
                description=f"Approval request expired: {request.operation}",
                metadata={
                    "request_id": request.request_id,
                    "final_state": request.state.value,
                },
            )

            processed.append(request)

        return processed


# Singleton accessor
_workflow_instance: Optional[ApprovalWorkflow] = None


def get_approval_workflow() -> ApprovalWorkflow:
    """Get the singleton approval workflow instance."""
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = ApprovalWorkflow()
    return _workflow_instance
