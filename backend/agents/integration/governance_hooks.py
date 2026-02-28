"""
Governance Lifecycle Hooks
Integration hooks for agent and mission lifecycle events

Built with Pride for Obex Blackvault
"""

import uuid
from typing import Dict, Any, Optional
from datetime import datetime
import logging

from backend.database.session import get_db
from backend.database.repositories import (
    AssetRepository,
    LineageRepository,
    AuditRepository,
    ApprovalRepository,
)
from backend.database.governance_models import (
    AssetType,
    RiskTier,
    ApprovalStatus,
    AuthorityLevel,
)
from backend.database.cache_manager import cache_manager
from backend.agents.integration.nats_governance import governance_nats

logger = logging.getLogger(__name__)


class GovernanceHooks:
    """
    Lifecycle hooks for governance integration

    Hooks into agent and mission lifecycle to:
    - Auto-register assets
    - Track lineage
    - Enforce policies
    - Audit events
    """

    @staticmethod
    async def on_agent_created(
        agent_id: str,
        agent_type: str,
        tenant_id: str,
        owner_id: str,
        name: str,
        model: str,
        capabilities: list,
        config: dict,
        db=None,
    ) -> None:
        """
        Hook called when agent is created

        Actions:
        - Register in governance asset registry
        - Calculate initial risk score
        - Apply default tags
        - Create lineage event
        - Audit log

        Args:
            agent_id: Agent ID
            agent_type: Agent type
            tenant_id: Tenant ID
            owner_id: Owner user ID
            name: Agent name
            model: LLM model used
            capabilities: List of capabilities
            config: Agent configuration
        """
        try:
            if db is None:
                db = next(get_db())

            # Register asset
            asset_repo = AssetRepository(db)
            _ = asset_repo.create_asset(
                id=agent_id,
                name=name,
                asset_type=AssetType.AGENT,
                owner_id=owner_id,
                tenant_id=tenant_id,
                description=f"{agent_type} agent using {model}",
                version="1.0.0",
                tags=["agent", agent_type.lower()],
                asset_metadata={
                    "model": model,
                    "capabilities": capabilities,
                    "config": config,
                },
            )

            # Create lineage event
            lineage_repo = LineageRepository(db)
            lineage_repo.create_event(
                id=str(uuid.uuid4()),
                asset_id=agent_id,
                event_type="created",
                actor_id=owner_id,
                event_data={
                    "agent_type": agent_type,
                    "model": model,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            # Create audit event
            audit_repo = AuditRepository(db)
            audit_repo.create_event(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_type="agent_created",
                event_category="lifecycle",
                severity="info",
                actor_id=owner_id,
                actor_type="user",
                outcome="success",
                asset_id=agent_id,
                event_data={"agent_type": agent_type, "model": model},
            )

            # Commit changes
            db.commit()

            # Trigger async risk calculation
            await governance_nats.publish_risk_recalculation(
                agent_id,
                "initial_assessment",
                {"agent_type": agent_type, "model": model},
            )

            logger.info(f"Governance: Registered agent {agent_id}")

        except Exception as e:
            logger.error(f"Governance hook failed for agent {agent_id}: {e}")
            # Don't fail agent creation if governance fails

    @staticmethod
    async def on_agent_updated(
        agent_id: str, tenant_id: str, actor_id: str, changes: Dict[str, Any], db=None
    ) -> None:
        """
        Hook called when agent is updated

        Actions:
        - Update asset metadata
        - Create lineage event
        - Recalculate risk if needed
        - Invalidate caches
        - Audit log

        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            actor_id: User who made the change
            changes: Dictionary of changed fields
        """
        try:
            if db is None:
                db = next(get_db())

            # Update asset
            asset_repo = AssetRepository(db)
            asset = asset_repo.get(agent_id)
            if not asset:
                logger.warning(f"Asset {agent_id} not found in governance")
                return

            # Update metadata with changes
            asset_metadata = asset.asset_metadata or {}
            asset_metadata.update(changes)
            asset_repo.update(agent_id, asset_metadata=asset_metadata)

            # Create lineage event
            lineage_repo = LineageRepository(db)
            lineage_repo.create_event(
                id=str(uuid.uuid4()),
                asset_id=agent_id,
                event_type="updated",
                actor_id=actor_id,
                event_data={
                    "changes": changes,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            # Create audit event
            audit_repo = AuditRepository(db)
            audit_repo.create_event(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_type="agent_updated",
                event_category="modification",
                severity="info",
                actor_id=actor_id,
                actor_type="user",
                outcome="success",
                asset_id=agent_id,
                event_data={"changes": changes},
            )

            # Commit changes
            db.commit()

            # Invalidate caches
            cache_manager.invalidate_asset(agent_id)

            # Recalculate risk if significant change
            significant_changes = ["model", "capabilities", "permissions"]
            if any(key in changes for key in significant_changes):
                await governance_nats.publish_risk_recalculation(
                    agent_id, "configuration_change", {"changes": changes}
                )

            logger.info(f"Governance: Updated agent {agent_id}")

        except Exception as e:
            logger.error(f"Governance hook failed for agent {agent_id}: {e}")

    @staticmethod
    async def on_agent_deleted(
        agent_id: str, tenant_id: str, actor_id: str, db=None
    ) -> None:
        """
        Hook called when agent is deleted

        Actions:
        - Archive asset (soft delete)
        - Create lineage event
        - Check for dependent assets
        - Invalidate caches
        - Audit log

        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            actor_id: User who deleted
        """
        try:
            if db is None:
                db = next(get_db())

            # Archive asset
            asset_repo = AssetRepository(db)
            asset_repo.archive_asset(agent_id)

            # Create lineage event
            lineage_repo = LineageRepository(db)
            lineage_repo.create_event(
                id=str(uuid.uuid4()),
                asset_id=agent_id,
                event_type="deleted",
                actor_id=actor_id,
                event_data={"timestamp": datetime.utcnow().isoformat()},
            )

            # Create audit event
            audit_repo = AuditRepository(db)
            audit_repo.create_event(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_type="agent_deleted",
                event_category="lifecycle",
                severity="warning",
                actor_id=actor_id,
                actor_type="user",
                outcome="success",
                asset_id=agent_id,
            )

            # Commit changes
            db.commit()

            # Check for dependents
            dependents = asset_repo.get_dependents(agent_id)
            if dependents:
                await governance_nats.publish_alert(
                    "warning",
                    f"Agent {agent_id} deleted with {len(dependents)} dependents",
                    f"Assets depending on deleted agent: {[d.id for d in dependents]}",
                    agent_id,
                )

            # Invalidate caches
            cache_manager.invalidate_asset(agent_id)

            logger.info(f"Governance: Archived agent {agent_id}")

        except Exception as e:
            logger.error(f"Governance hook failed for agent deletion {agent_id}: {e}")

    @staticmethod
    async def on_mission_started(
        mission_id: str,
        agent_id: str,
        tenant_id: str,
        objective: str,
        context: Dict[str, Any],
        db=None,
    ) -> bool:
        """
        Hook called before mission execution starts

        Actions:
        - Check agent compliance status
        - Evaluate applicable policies
        - Require approval if high-risk
        - Audit log

        Args:
            mission_id: Mission ID
            agent_id: Agent ID
            tenant_id: Tenant ID
            objective: Mission objective
            context: Mission context

        Returns:
            True if mission can proceed, False if blocked
        """
        try:
            if db is None:
                db = next(get_db())

            # Get asset
            asset_repo = AssetRepository(db)
            asset = asset_repo.get(agent_id)
            if not asset:
                logger.warning(f"Agent {agent_id} not in governance registry")
                return True  # Allow if not registered

            # Check compliance status
            if asset.compliance_status == "non_compliant":
                logger.warning(f"Mission blocked: Agent {agent_id} is non-compliant")

                audit_repo = AuditRepository(db)
                audit_repo.create_event(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    event_type="mission_blocked",
                    event_category="compliance",
                    severity="warning",
                    actor_id=agent_id,
                    actor_type="agent",
                    outcome="blocked",
                    asset_id=agent_id,
                    event_data={
                        "mission_id": mission_id,
                        "reason": "non_compliant_agent",
                    },
                )

                return False

            # Check risk tier — high-risk and unacceptable agents require an approved
            # governance approval before executing any mission.
            if asset.risk_tier in [RiskTier.HIGH, RiskTier.UNACCEPTABLE]:
                approval_repo = ApprovalRepository(db)

                # Look for an existing pending or approved approval for this asset
                existing = approval_repo.get_by_asset(
                    asset_id=agent_id, status=ApprovalStatus.APPROVED
                )

                if not existing:
                    # No approved entry — check for a pending one to avoid duplicates
                    pending = approval_repo.get_by_asset(
                        asset_id=agent_id, status=ApprovalStatus.PENDING
                    )

                    if not pending:
                        # Create a new approval request so a compliance officer can review
                        required_authority = (
                            AuthorityLevel.COMPLIANCE_OFFICER
                            if asset.risk_tier == RiskTier.UNACCEPTABLE
                            else AuthorityLevel.ADMIN
                        )
                        approval_repo.create_approval_request(
                            id=str(uuid.uuid4()),
                            asset_id=agent_id,
                            tenant_id=tenant_id,
                            request_type="mission_execution",
                            requested_by=agent_id,
                            required_authority=required_authority,
                            risk_tier=asset.risk_tier,
                            context={
                                "mission_id": mission_id,
                                "objective": objective[:200],
                                "risk_tier": asset.risk_tier.value,
                            },
                        )
                        db.commit()
                        logger.warning(
                            f"Mission blocked: high-risk agent {agent_id} has no approved "
                            f"approval for mission {mission_id}. Approval request created."
                        )

                        audit_repo = AuditRepository(db)
                        audit_repo.create_event(
                            id=str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            event_type="mission_blocked",
                            event_category="compliance",
                            severity="warning",
                            actor_id=agent_id,
                            actor_type="agent",
                            outcome="blocked",
                            asset_id=agent_id,
                            event_data={
                                "mission_id": mission_id,
                                "reason": "approval_required",
                                "risk_tier": asset.risk_tier.value,
                            },
                        )
                        db.commit()
                        return False

                    # A pending approval exists — still blocked until it is approved
                    logger.warning(
                        f"Mission blocked: agent {agent_id} has a pending approval "
                        f"(not yet approved) for mission {mission_id}."
                    )
                    return False

                # Approved entry found — allow mission to proceed
                logger.info(
                    f"High-risk agent {agent_id} cleared by approval "
                    f"{existing[0].id} for mission {mission_id}."
                )

            # Create audit event
            audit_repo = AuditRepository(db)
            audit_repo.create_event(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_type="mission_started",
                event_category="execution",
                severity="info",
                actor_id=agent_id,
                actor_type="agent",
                outcome="success",
                asset_id=agent_id,
                event_data={
                    "mission_id": mission_id,
                    "objective": objective[:100],  # Truncate
                },
            )

            # Commit changes
            db.commit()

            return True

        except Exception as e:
            logger.error(f"Governance hook failed for mission start: {e}")
            return True  # Allow on error

    @staticmethod
    async def on_mission_completed(
        mission_id: str,
        agent_id: str,
        tenant_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        db=None,
    ) -> None:
        """
        Hook called after mission execution completes

        Actions:
        - Update agent performance metrics
        - Create lineage event
        - Adjust risk score if needed
        - Audit log

        Args:
            mission_id: Mission ID
            agent_id: Agent ID
            tenant_id: Tenant ID
            status: Mission status (success, failure, etc.)
            result: Mission result
            error: Error message if failed
        """
        try:
            if db is None:
                db = next(get_db())

            # Create lineage event
            lineage_repo = LineageRepository(db)
            lineage_repo.create_event(
                id=str(uuid.uuid4()),
                asset_id=agent_id,
                event_type="mission_completed",
                actor_id=agent_id,
                event_data={
                    "mission_id": mission_id,
                    "status": status,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )

            # Create audit event
            audit_repo = AuditRepository(db)
            severity = "error" if status == "failure" else "info"
            audit_repo.create_event(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                event_type="mission_completed",
                event_category="execution",
                severity=severity,
                actor_id=agent_id,
                actor_type="agent",
                outcome=status,
                asset_id=agent_id,
                event_data={"mission_id": mission_id, "status": status, "error": error},
            )

            # Commit changes
            db.commit()

            # Trigger risk recalculation if failure
            if status == "failure":
                await governance_nats.publish_risk_recalculation(
                    agent_id,
                    "mission_failure",
                    {"mission_id": mission_id, "error": error},
                )

            logger.info(
                f"Governance: Mission {mission_id} completed with status {status}"
            )

        except Exception as e:
            logger.error(f"Governance hook failed for mission completion: {e}")


# Global hooks instance
governance_hooks = GovernanceHooks()
