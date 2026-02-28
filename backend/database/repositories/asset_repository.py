"""
Asset Repository
Database operations for governance assets

Built with Pride for Obex Blackvault
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import datetime

from backend.database.governance_models import (
    GovernanceAsset,
    AssetType,
    AssetStatus,
    RiskTier,
    ComplianceStatus,
)
from backend.database.repositories.base import BaseRepository


class AssetRepository(BaseRepository[GovernanceAsset]):
    """Repository for governance asset operations"""

    def __init__(self, db: Session):
        super().__init__(db, GovernanceAsset)

    def create_asset(
        self,
        id: str,
        name: str,
        asset_type: AssetType,
        owner_id: str,
        tenant_id: str,
        description: Optional[str] = None,
        version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        asset_metadata: Optional[Dict[str, Any]] = None,
        dependencies: Optional[List[str]] = None,
        status: AssetStatus = AssetStatus.ACTIVE,
        risk_tier: Optional[RiskTier] = None,
        risk_score: Optional[float] = None,
        compliance_status: Optional[ComplianceStatus] = None,
    ) -> GovernanceAsset:
        """
        Create new governance asset

        Args:
            id: Unique asset identifier
            name: Asset name
            asset_type: Type of asset (agent, tool, model, etc.)
            owner_id: Owner user ID
            tenant_id: Tenant ID
            description: Optional description
            version: Optional version string
            tags: Optional list of tags
            asset_metadata: Optional metadata dictionary
            dependencies: Optional list of dependency asset IDs
            status: Asset status (default: active)
            risk_tier: Optional initial risk tier
            risk_score: Optional initial risk score
            compliance_status: Optional initial compliance status

        Returns:
            Created GovernanceAsset instance
        """
        kwargs: Dict[str, Any] = dict(
            id=id,
            name=name,
            asset_type=asset_type,
            status=status,
            owner_id=owner_id,
            tenant_id=tenant_id,
            description=description,
            version=version,
            tags=tags or [],
            asset_metadata=asset_metadata or {},
            dependencies=dependencies or [],
        )
        if risk_tier is not None:
            kwargs["risk_tier"] = risk_tier
        if risk_score is not None:
            kwargs["risk_score"] = risk_score
        if compliance_status is not None:
            kwargs["compliance_status"] = compliance_status
        return self.create(**kwargs)

    def get_by_tenant(
        self,
        tenant_id: str,
        asset_type: Optional[AssetType] = None,
        status: Optional[AssetStatus] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GovernanceAsset]:
        """
        Get assets by tenant with optional filters

        Args:
            tenant_id: Tenant ID
            asset_type: Optional asset type filter
            status: Optional status filter
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAsset instances
        """
        query = self.db.query(GovernanceAsset).filter(
            GovernanceAsset.tenant_id == tenant_id
        )

        if asset_type:
            query = query.filter(GovernanceAsset.asset_type == asset_type)

        if status:
            query = query.filter(GovernanceAsset.status == status)

        return (
            query.order_by(GovernanceAsset.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_by_owner(
        self, owner_id: str, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> List[GovernanceAsset]:
        """
        Get assets by owner

        Args:
            owner_id: Owner user ID
            tenant_id: Tenant ID
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAsset instances
        """
        return (
            self.db.query(GovernanceAsset)
            .filter(
                and_(
                    GovernanceAsset.owner_id == owner_id,
                    GovernanceAsset.tenant_id == tenant_id,
                )
            )
            .order_by(GovernanceAsset.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_by_risk_tier(
        self, tenant_id: str, risk_tier: RiskTier, limit: int = 100, offset: int = 0
    ) -> List[GovernanceAsset]:
        """
        Get assets by risk tier

        Args:
            tenant_id: Tenant ID
            risk_tier: Risk tier to filter by
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAsset instances
        """
        return (
            self.db.query(GovernanceAsset)
            .filter(
                and_(
                    GovernanceAsset.tenant_id == tenant_id,
                    GovernanceAsset.risk_tier == risk_tier,
                )
            )
            .order_by(GovernanceAsset.risk_score.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def get_high_risk_assets(
        self, tenant_id: str, limit: int = 100
    ) -> List[GovernanceAsset]:
        """
        Get high and unacceptable risk assets

        Args:
            tenant_id: Tenant ID
            limit: Maximum results

        Returns:
            List of high-risk GovernanceAsset instances
        """
        return (
            self.db.query(GovernanceAsset)
            .filter(
                and_(
                    GovernanceAsset.tenant_id == tenant_id,
                    GovernanceAsset.risk_tier.in_(
                        [RiskTier.HIGH, RiskTier.UNACCEPTABLE]
                    ),
                )
            )
            .order_by(GovernanceAsset.risk_score.desc())
            .limit(limit)
            .all()
        )

    def get_by_compliance_status(
        self,
        tenant_id: str,
        compliance_status: ComplianceStatus,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GovernanceAsset]:
        """
        Get assets by compliance status

        Args:
            tenant_id: Tenant ID
            compliance_status: Compliance status to filter by
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAsset instances
        """
        return (
            self.db.query(GovernanceAsset)
            .filter(
                and_(
                    GovernanceAsset.tenant_id == tenant_id,
                    GovernanceAsset.compliance_status == compliance_status,
                )
            )
            .order_by(GovernanceAsset.updated_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def search_by_tags(
        self,
        tenant_id: str,
        tags: List[str],
        match_all: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> List[GovernanceAsset]:
        """
        Search assets by tags

        Args:
            tenant_id: Tenant ID
            tags: List of tags to search for
            match_all: If True, asset must have all tags; if False, any tag
            limit: Maximum results
            offset: Results offset

        Returns:
            List of GovernanceAsset instances
        """
        query = self.db.query(GovernanceAsset).filter(
            GovernanceAsset.tenant_id == tenant_id
        )

        if match_all:
            # Asset must have all tags
            for tag in tags:
                query = query.filter(GovernanceAsset.tags.contains([tag]))
        else:
            # Asset must have at least one tag
            query = query.filter(GovernanceAsset.tags.overlap(tags))

        return (
            query.order_by(GovernanceAsset.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )

    def update_risk_assessment(
        self, asset_id: str, risk_tier: RiskTier, risk_score: float
    ) -> GovernanceAsset:
        """
        Update asset risk assessment

        Args:
            asset_id: Asset ID
            risk_tier: New risk tier
            risk_score: New risk score

        Returns:
            Updated GovernanceAsset instance
        """
        return self.update(
            asset_id,
            risk_tier=risk_tier,
            risk_score=risk_score,
            last_assessed_at=datetime.utcnow(),
        )

    def update_compliance_status(
        self, asset_id: str, compliance_status: ComplianceStatus
    ) -> GovernanceAsset:
        """
        Update asset compliance status

        Args:
            asset_id: Asset ID
            compliance_status: New compliance status

        Returns:
            Updated GovernanceAsset instance
        """
        return self.update(
            asset_id,
            compliance_status=compliance_status,
            last_assessed_at=datetime.utcnow(),
        )

    def add_tag(self, asset_id: str, tag: str) -> GovernanceAsset:
        """
        Add tag to asset.

        Uses list replacement (not in-place mutation) so SQLAlchemy
        detects the JSON column change and persists it correctly.

        Args:
            asset_id: Asset ID
            tag: Tag to add

        Returns:
            Updated GovernanceAsset instance
        """
        asset = self.get_or_raise(asset_id)
        if tag not in asset.tags:
            # Replace the list — do NOT mutate in-place.
            # SQLAlchemy tracks JSON column changes by object identity;
            # appending to the existing list doesn't mark it as dirty.
            asset.tags = list(asset.tags) + [tag]
            self.db.commit()
            self.db.refresh(asset)
        return asset

    def remove_tag(self, asset_id: str, tag: str) -> GovernanceAsset:
        """
        Remove tag from asset.

        Uses list replacement (not in-place mutation) so SQLAlchemy
        detects the JSON column change and persists it correctly.

        Args:
            asset_id: Asset ID
            tag: Tag to remove

        Returns:
            Updated GovernanceAsset instance
        """
        asset = self.get_or_raise(asset_id)
        if tag in asset.tags:
            # Replace the list — do NOT mutate in-place.
            asset.tags = [t for t in asset.tags if t != tag]
            self.db.commit()
            self.db.refresh(asset)
        return asset

    def add_dependency(self, asset_id: str, dependency_id: str) -> GovernanceAsset:
        """
        Add dependency to asset

        Args:
            asset_id: Asset ID
            dependency_id: Dependency asset ID

        Returns:
            Updated GovernanceAsset instance
        """
        asset = self.get_or_raise(asset_id)
        if dependency_id not in asset.dependencies:
            # Replace the list — do NOT mutate in-place.
            asset.dependencies = list(asset.dependencies) + [dependency_id]
            self.db.commit()
            self.db.refresh(asset)
        return asset

    def get_dependents(self, asset_id: str) -> List[GovernanceAsset]:
        """
        Get assets that depend on this asset

        Args:
            asset_id: Asset ID

        Returns:
            List of dependent GovernanceAsset instances
        """
        return (
            self.db.query(GovernanceAsset)
            .filter(GovernanceAsset.dependencies.contains([asset_id]))
            .all()
        )

    def archive_asset(self, asset_id: str) -> GovernanceAsset:
        """
        Archive asset (soft delete)

        Args:
            asset_id: Asset ID

        Returns:
            Updated GovernanceAsset instance
        """
        return self.update(asset_id, status=AssetStatus.ARCHIVED)

    def get_statistics(self, tenant_id: str) -> Dict[str, Any]:
        """
        Get asset statistics for tenant

        Args:
            tenant_id: Tenant ID

        Returns:
            Dictionary with statistics
        """
        total = self.count({"tenant_id": tenant_id})

        # Count by type
        by_type = {}
        for asset_type in AssetType:
            count = self.count({"tenant_id": tenant_id, "asset_type": asset_type})
            by_type[asset_type.value] = count

        # Count by status
        by_status = {}
        for status in AssetStatus:
            count = self.count({"tenant_id": tenant_id, "status": status})
            by_status[status.value] = count

        # Count by risk tier
        by_risk = {}
        for risk_tier in RiskTier:
            count = (
                self.db.query(GovernanceAsset)
                .filter(
                    and_(
                        GovernanceAsset.tenant_id == tenant_id,
                        GovernanceAsset.risk_tier == risk_tier,
                    )
                )
                .count()
            )
            by_risk[risk_tier.value] = count

        return {
            "total": total,
            "by_type": by_type,
            "by_status": by_status,
            "by_risk": by_risk,
        }
