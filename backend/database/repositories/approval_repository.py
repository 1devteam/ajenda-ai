"""
Approval Repository
Database operations for governance approval workflows

Built with Pride for Obex Blackvault
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from datetime import datetime, timedelta

from backend.database.governance_models import (
    GovernanceApproval,
    ApprovalStatus,
    AuthorityLevel,
    RiskTier,
)
from backend.database.repositories.base import BaseRepository


class ApprovalRepository(BaseRepository[GovernanceApproval]):
    """Repository for approval workflow operations"""

    def __init__(self, db: Session):
        super().__init__(db, GovernanceApproval)

    def create_approval_request(
        self,
        id: str,
        asset_id: str,
        tenant_id: str,
        request_type: str,
        requested_by: str,
        required_authority: AuthorityLevel,
        risk_tier: RiskTier,
        approvers: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        expires_at: Optional[datetime] = None,
    ) -> GovernanceApproval:
        """
        Create approval request

        Args:
            id: Approval ID
            asset_id: Asset ID
            tenant_id: Tenant ID
            request_type: Type of request (deployment, modification, access, etc.)
            requested_by: Requester user ID
            required_authority: Required authority level
            risk_tier: Risk tier of operation
            approvers: Optional list of approver IDs
            context: Optional request context
            expires_at: Optional expiration datetime

        Returns:
            Created GovernanceApproval instance
        """
        return self.create(
            id=id,
            asset_id=asset_id,
            tenant_id=tenant_id,
            request_type=request_type,
            requested_by=requested_by,
            required_authority=required_authority,
            status=ApprovalStatus.PENDING,
            risk_tier=risk_tier,
            approvers=approvers or [],
            context=context or {},
            expires_at=expires_at,
        )

    def get_pending_approvals(
        self,
        tenant_id: str,
        authority_level: Optional[AuthorityLevel] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GovernanceApproval]:
        """
        Get pending approval requests

        Args:
            tenant_id: Tenant ID
            authority_level: Optional authority level filter
            limit: Maximum results
            offset: Results offset

        Returns:
            List of pending GovernanceApproval instances
        """
        query = self.db.query(GovernanceApproval).filter(
            and_(
                GovernanceApproval.tenant_id == tenant_id,
                GovernanceApproval.status == ApprovalStatus.PENDING,
            )
        )

        if authority_level:
            query = query.filter(GovernanceApproval.required_authority == authority_level)

        return query.order_by(GovernanceApproval.requested_at).limit(limit).offset(offset).all()

    def get_by_asset(
        self, asset_id: str, status: Optional[ApprovalStatus] = None, limit: int = 100
    ) -> List[GovernanceApproval]:
        """
        Get approval requests for asset

        Args:
            asset_id: Asset ID
            status: Optional status filter
            limit: Maximum results

        Returns:
            List of GovernanceApproval instances
        """
        query = self.db.query(GovernanceApproval).filter(GovernanceApproval.asset_id == asset_id)

        if status:
            query = query.filter(GovernanceApproval.status == status)

        return query.order_by(desc(GovernanceApproval.requested_at)).limit(limit).all()

    def get_by_requester(
        self,
        requested_by: str,
        tenant_id: str,
        status: Optional[ApprovalStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GovernanceApproval]:
        """
        Get approval requests by requester

        Args:
            requested_by: Requester user ID
            tenant_id: Tenant ID
            status: Optional status filter
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceApproval instances
        """
        query = self.db.query(GovernanceApproval).filter(
            and_(
                GovernanceApproval.requested_by == requested_by,
                GovernanceApproval.tenant_id == tenant_id,
            )
        )

        if status:
            query = query.filter(GovernanceApproval.status == status)

        return (
            query.order_by(desc(GovernanceApproval.requested_at)).limit(limit).offset(offset).all()
        )

    def get_by_approver(
        self,
        approver_id: str,
        tenant_id: str,
        status: ApprovalStatus = ApprovalStatus.PENDING,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GovernanceApproval]:
        """
        Get approval requests assigned to approver

        Args:
            approver_id: Approver user ID
            tenant_id: Tenant ID
            status: Status filter (default: pending)
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceApproval instances
        """
        return (
            self.db.query(GovernanceApproval)
            .filter(
                and_(
                    GovernanceApproval.tenant_id == tenant_id,
                    GovernanceApproval.status == status,
                    GovernanceApproval.approvers.contains([approver_id]),
                )
            )
            .order_by(GovernanceApproval.requested_at)
            .limit(limit)
            .offset(offset)
            .all()
        )

    def approve_request(self, approval_id: str, approved_by: str) -> GovernanceApproval:
        """
        Approve request

        Args:
            approval_id: Approval ID
            approved_by: Approver user ID

        Returns:
            Updated GovernanceApproval instance
        """
        return self.update(
            approval_id,
            status=ApprovalStatus.APPROVED,
            approved_by=approved_by,
            approved_at=datetime.utcnow(),
        )

    def reject_request(self, approval_id: str, rejected_by: str, reason: str) -> GovernanceApproval:
        """
        Reject request

        Args:
            approval_id: Approval ID
            rejected_by: Rejector user ID
            reason: Rejection reason

        Returns:
            Updated GovernanceApproval instance
        """
        return self.update(
            approval_id,
            status=ApprovalStatus.REJECTED,
            approved_by=rejected_by,
            approved_at=datetime.utcnow(),
            rejection_reason=reason,
        )

    def escalate_request(self, approval_id: str, new_approvers: List[str]) -> GovernanceApproval:
        """
        Escalate request to higher authority

        Args:
            approval_id: Approval ID
            new_approvers: New list of approvers

        Returns:
            Updated GovernanceApproval instance
        """
        return self.update(approval_id, status=ApprovalStatus.ESCALATED, approvers=new_approvers)

    def expire_old_requests(self, tenant_id: str) -> int:
        """
        Mark expired requests as expired

        Args:
            tenant_id: Tenant ID

        Returns:
            Number of expired requests
        """
        now = datetime.utcnow()
        expired = (
            self.db.query(GovernanceApproval)
            .filter(
                and_(
                    GovernanceApproval.tenant_id == tenant_id,
                    GovernanceApproval.status == ApprovalStatus.PENDING,
                    GovernanceApproval.expires_at.isnot(None),
                    GovernanceApproval.expires_at < now,
                )
            )
            .all()
        )

        count = 0
        for approval in expired:
            approval.status = ApprovalStatus.EXPIRED
            count += 1

        if count > 0:
            self.db.commit()

        return count

    def get_approval_queue_depth(self, tenant_id: str, risk_tier: Optional[RiskTier] = None) -> int:
        """
        Get number of pending approvals

        Args:
            tenant_id: Tenant ID
            risk_tier: Optional risk tier filter

        Returns:
            Number of pending approvals
        """
        query = self.db.query(GovernanceApproval).filter(
            and_(
                GovernanceApproval.tenant_id == tenant_id,
                GovernanceApproval.status == ApprovalStatus.PENDING,
            )
        )

        if risk_tier:
            query = query.filter(GovernanceApproval.risk_tier == risk_tier)

        return query.count()

    def get_statistics(self, tenant_id: str, days: int = 30) -> Dict[str, Any]:
        """
        Get approval statistics

        Args:
            tenant_id: Tenant ID
            days: Time window in days

        Returns:
            Dictionary with statistics
        """
        cutoff = datetime.utcnow() - timedelta(days=days)

        # Total requests
        total = (
            self.db.query(GovernanceApproval)
            .filter(
                and_(
                    GovernanceApproval.tenant_id == tenant_id,
                    GovernanceApproval.requested_at >= cutoff,
                )
            )
            .count()
        )

        # By status
        by_status = {}
        for status in ApprovalStatus:
            count = (
                self.db.query(GovernanceApproval)
                .filter(
                    and_(
                        GovernanceApproval.tenant_id == tenant_id,
                        GovernanceApproval.status == status,
                        GovernanceApproval.requested_at >= cutoff,
                    )
                )
                .count()
            )
            by_status[status.value] = count

        # By risk tier
        by_risk = {}
        for risk_tier in RiskTier:
            count = (
                self.db.query(GovernanceApproval)
                .filter(
                    and_(
                        GovernanceApproval.tenant_id == tenant_id,
                        GovernanceApproval.risk_tier == risk_tier,
                        GovernanceApproval.requested_at >= cutoff,
                    )
                )
                .count()
            )
            by_risk[risk_tier.value] = count

        # Average approval time (for approved requests)
        approved = (
            self.db.query(GovernanceApproval)
            .filter(
                and_(
                    GovernanceApproval.tenant_id == tenant_id,
                    GovernanceApproval.status == ApprovalStatus.APPROVED,
                    GovernanceApproval.requested_at >= cutoff,
                )
            )
            .all()
        )

        avg_approval_time_seconds = None
        if approved:
            total_time = sum(
                [
                    (a.approved_at - a.requested_at).total_seconds()
                    for a in approved
                    if a.approved_at
                ]
            )
            avg_approval_time_seconds = total_time / len(approved) if approved else 0

        return {
            "total": total,
            "by_status": by_status,
            "by_risk": by_risk,
            "avg_approval_time_seconds": avg_approval_time_seconds,
            "time_window_days": days,
        }
