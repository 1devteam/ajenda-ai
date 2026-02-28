"""
Policy Repository
Database operations for governance policies

Built with Pride for Obex Blackvault
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc
from datetime import datetime, timedelta

from backend.database.governance_models import (
    GovernancePolicy,
    GovernancePolicyEvaluation,
    PolicyStatus,
)
from backend.database.repositories.base import BaseRepository


class PolicyRepository(BaseRepository[GovernancePolicy]):
    """Repository for policy operations"""

    def __init__(self, db: Session):
        super().__init__(db, GovernancePolicy)

    def create_policy(
        self,
        id: str,
        name: str,
        tenant_id: str,
        created_by: str,
        rules: Dict[str, Any],
        description: Optional[str] = None,
        status: PolicyStatus = PolicyStatus.DRAFT,
        priority: int = 0,
        applies_to: Optional[List[str]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        actions: Optional[Dict[str, Any]] = None,
    ) -> GovernancePolicy:
        """
        Create governance policy

        Args:
            id: Policy ID
            name: Policy name
            tenant_id: Tenant ID
            created_by: Creator user ID
            rules: Policy rules
            description: Optional description
            status: Policy status (default: draft)
            priority: Priority (higher = more important)
            applies_to: Optional list of asset types or IDs
            conditions: Optional evaluation conditions
            actions: Optional actions on violation

        Returns:
            Created GovernancePolicy instance
        """
        return self.create(
            id=id,
            name=name,
            description=description,
            status=status,
            priority=priority,
            applies_to=applies_to or [],
            rules=rules,
            conditions=conditions or {},
            actions=actions or {},
            created_by=created_by,
            tenant_id=tenant_id,
        )

    def get_active_policies(
        self, tenant_id: str, applies_to: Optional[str] = None
    ) -> List[GovernancePolicy]:
        """
        Get active policies for tenant

        Args:
            tenant_id: Tenant ID
            applies_to: Optional asset type or ID filter

        Returns:
            List of active GovernancePolicy instances ordered by priority
        """
        query = self.db.query(GovernancePolicy).filter(
            and_(
                GovernancePolicy.tenant_id == tenant_id,
                GovernancePolicy.status == PolicyStatus.ACTIVE,
            )
        )

        if applies_to:
            query = query.filter(GovernancePolicy.applies_to.contains([applies_to]))

        return query.order_by(desc(GovernancePolicy.priority)).all()

    def get_by_status(
        self, tenant_id: str, status: PolicyStatus, limit: int = 100, offset: int = 0
    ) -> List[GovernancePolicy]:
        """
        Get policies by status

        Args:
            tenant_id: Tenant ID
            status: Policy status
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernancePolicy instances
        """
        return (
            self.db.query(GovernancePolicy)
            .filter(
                and_(
                    GovernancePolicy.tenant_id == tenant_id,
                    GovernancePolicy.status == status,
                )
            )
            .order_by(desc(GovernancePolicy.priority))
            .limit(limit)
            .offset(offset)
            .all()
        )

    def activate_policy(self, policy_id: str) -> GovernancePolicy:
        """
        Activate policy

        Args:
            policy_id: Policy ID

        Returns:
            Updated GovernancePolicy instance
        """
        return self.update(policy_id, status=PolicyStatus.ACTIVE)

    def deactivate_policy(self, policy_id: str) -> GovernancePolicy:
        """
        Deactivate policy

        Args:
            policy_id: Policy ID

        Returns:
            Updated GovernancePolicy instance
        """
        return self.update(policy_id, status=PolicyStatus.INACTIVE)

    def archive_policy(self, policy_id: str) -> GovernancePolicy:
        """
        Archive policy

        Args:
            policy_id: Policy ID

        Returns:
            Updated GovernancePolicy instance
        """
        return self.update(policy_id, status=PolicyStatus.ARCHIVED)

    def update_priority(self, policy_id: str, priority: int) -> GovernancePolicy:
        """
        Update policy priority

        Args:
            policy_id: Policy ID
            priority: New priority

        Returns:
            Updated GovernancePolicy instance
        """
        return self.update(policy_id, priority=priority)


class PolicyEvaluationRepository(BaseRepository[GovernancePolicyEvaluation]):
    """Repository for policy evaluation cache"""

    def __init__(self, db: Session):
        super().__init__(db, GovernancePolicyEvaluation)

    def create_evaluation(
        self,
        id: str,
        policy_id: str,
        asset_id: str,
        result: str,
        violations: Optional[List[Dict[str, Any]]] = None,
        recommendations: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> GovernancePolicyEvaluation:
        """
        Create policy evaluation result

        Args:
            id: Evaluation ID
            policy_id: Policy ID
            asset_id: Asset ID
            result: Evaluation result (allow, deny, warn)
            violations: Optional list of violations
            recommendations: Optional list of recommendations
            context: Optional evaluation context

        Returns:
            Created GovernancePolicyEvaluation instance
        """
        return self.create(
            id=id,
            policy_id=policy_id,
            asset_id=asset_id,
            result=result,
            violations=violations or [],
            recommendations=recommendations or [],
            context=context or {},
        )

    def get_asset_evaluations(
        self, asset_id: str, limit: int = 100
    ) -> List[GovernancePolicyEvaluation]:
        """
        Get all policy evaluations for asset

        Args:
            asset_id: Asset ID
            limit: Maximum results

        Returns:
            List of GovernancePolicyEvaluation instances
        """
        return (
            self.db.query(GovernancePolicyEvaluation)
            .filter(GovernancePolicyEvaluation.asset_id == asset_id)
            .order_by(desc(GovernancePolicyEvaluation.evaluated_at))
            .limit(limit)
            .all()
        )

    def get_policy_evaluations(
        self, policy_id: str, result: Optional[str] = None, limit: int = 100
    ) -> List[GovernancePolicyEvaluation]:
        """
        Get all evaluations for policy

        Args:
            policy_id: Policy ID
            result: Optional result filter (allow, deny, warn)
            limit: Maximum results

        Returns:
            List of GovernancePolicyEvaluation instances
        """
        query = self.db.query(GovernancePolicyEvaluation).filter(
            GovernancePolicyEvaluation.policy_id == policy_id
        )

        if result:
            query = query.filter(GovernancePolicyEvaluation.result == result)

        return query.order_by(desc(GovernancePolicyEvaluation.evaluated_at)).limit(limit).all()

    def get_cached_evaluation(
        self, policy_id: str, asset_id: str, max_age_minutes: int = 5
    ) -> Optional[GovernancePolicyEvaluation]:
        """
        Get cached evaluation if fresh enough

        Args:
            policy_id: Policy ID
            asset_id: Asset ID
            max_age_minutes: Maximum age in minutes

        Returns:
            GovernancePolicyEvaluation instance or None if not found or stale
        """
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        return (
            self.db.query(GovernancePolicyEvaluation)
            .filter(
                and_(
                    GovernancePolicyEvaluation.policy_id == policy_id,
                    GovernancePolicyEvaluation.asset_id == asset_id,
                    GovernancePolicyEvaluation.evaluated_at >= cutoff,
                )
            )
            .order_by(desc(GovernancePolicyEvaluation.evaluated_at))
            .first()
        )

    def delete_asset_evaluations(self, asset_id: str) -> int:
        """
        Delete all evaluations for asset (cache invalidation)

        Args:
            asset_id: Asset ID

        Returns:
            Number of deleted evaluations
        """
        count = (
            self.db.query(GovernancePolicyEvaluation)
            .filter(GovernancePolicyEvaluation.asset_id == asset_id)
            .delete()
        )
        self.db.commit()
        return count

    def delete_policy_evaluations(self, policy_id: str) -> int:
        """
        Delete all evaluations for policy (cache invalidation)

        Args:
            policy_id: Policy ID

        Returns:
            Number of deleted evaluations
        """
        count = (
            self.db.query(GovernancePolicyEvaluation)
            .filter(GovernancePolicyEvaluation.policy_id == policy_id)
            .delete()
        )
        self.db.commit()
        return count
