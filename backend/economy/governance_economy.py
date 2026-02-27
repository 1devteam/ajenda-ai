"""
Governance Economy Integration
Risk-based pricing and compliance rewards

Built with Pride for Obex Blackvault
"""
from typing import Dict, Any, Optional
import logging

from backend.database.session import get_db
from backend.database.repositories import AssetRepository
from backend.database.governance_models import RiskTier, ComplianceStatus

logger = logging.getLogger(__name__)


class GovernanceEconomy:
    """
    Integrates governance with economy system
    
    Features:
    - Risk-based pricing (high-risk operations cost more)
    - Compliance rewards (compliant agents earn bonuses)
    - Policy violation penalties
    - Approval request costs
    """
    
    # Cost multipliers by risk tier
    RISK_MULTIPLIERS = {
        RiskTier.MINIMAL: 1.0,
        RiskTier.LIMITED: 1.2,
        RiskTier.HIGH: 1.5,
        RiskTier.UNACCEPTABLE: 2.0
    }
    
    # Compliance rewards (credits per mission)
    COMPLIANCE_REWARDS = {
        ComplianceStatus.COMPLIANT: 10.0,
        ComplianceStatus.NEEDS_REVIEW: 0.0,
        ComplianceStatus.NON_COMPLIANT: -20.0,  # Penalty
        ComplianceStatus.EXEMPTED: 0.0
    }
    
    # Approval request costs
    APPROVAL_COSTS = {
        "deployment": 50.0,
        "modification": 30.0,
        "access": 10.0,
        "escalation": 100.0
    }
    
    @staticmethod
    def calculate_mission_cost(
        base_cost: float,
        agent_id: str,
        tenant_id: str,
        db=None
    ) -> Dict[str, Any]:
        """
        Calculate mission cost with governance adjustments
        
        Args:
            base_cost: Base mission cost
            agent_id: Agent ID
            tenant_id: Tenant ID
            
        Returns:
            Dictionary with cost breakdown
        """
        try:
            if db is None:
                db = next(get_db())
            asset_repo = AssetRepository(db)
            
            # Get asset
            asset = asset_repo.get(agent_id)
            if not asset:
                logger.warning(f"Agent {agent_id} not in governance registry")
                return {
                    "base_cost": base_cost,
                    "risk_multiplier": 1.0,
                    "final_cost": base_cost,
                    "governance_applied": False
                }
            
            # Apply risk multiplier
            risk_multiplier = GovernanceEconomy.RISK_MULTIPLIERS.get(
                asset.risk_tier,
                1.0
            )
            
            final_cost = base_cost * risk_multiplier
            
            return {
                "base_cost": base_cost,
                "risk_tier": asset.risk_tier.value if asset.risk_tier else "unknown",
                "risk_multiplier": risk_multiplier,
                "final_cost": final_cost,
                "governance_applied": True
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate governance cost: {e}")
            return {
                "base_cost": base_cost,
                "risk_multiplier": 1.0,
                "final_cost": base_cost,
                "governance_applied": False,
                "error": str(e)
            }
    
    @staticmethod
    def calculate_compliance_reward(
        agent_id: str,
        tenant_id: str,
        db=None
    ) -> Dict[str, Any]:
        """
        Calculate compliance reward/penalty for agent
        
        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            
        Returns:
            Dictionary with reward amount
        """
        try:
            if db is None:
                db = next(get_db())
            asset_repo = AssetRepository(db)
            
            # Get asset
            asset = asset_repo.get(agent_id)
            if not asset:
                return {
                    "agent_id": agent_id,
                    "reward": 0.0,
                    "reason": "not_registered"
                }
            
            # Get reward based on compliance status
            reward = GovernanceEconomy.COMPLIANCE_REWARDS.get(
                asset.compliance_status,
                0.0
            )
            
            return {
                "agent_id": agent_id,
                "compliance_status": asset.compliance_status.value if asset.compliance_status else "unknown",
                "reward": reward,
                "reason": "compliance_reward" if reward > 0 else "compliance_penalty" if reward < 0 else "no_reward"
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate compliance reward: {e}")
            return {
                "agent_id": agent_id,
                "reward": 0.0,
                "reason": "error",
                "error": str(e)
            }
    
    @staticmethod
    def calculate_approval_cost(
        request_type: str,
        risk_tier: RiskTier
    ) -> float:
        """
        Calculate cost for approval request
        
        Args:
            request_type: Type of approval request
            risk_tier: Risk tier of operation
            
        Returns:
            Cost in credits
        """
        base_cost = GovernanceEconomy.APPROVAL_COSTS.get(request_type, 20.0)
        
        # Higher risk = higher approval cost
        risk_multiplier = GovernanceEconomy.RISK_MULTIPLIERS.get(risk_tier, 1.0)
        
        return base_cost * risk_multiplier
    
    @staticmethod
    def calculate_policy_violation_penalty(
        severity: str,
        violation_count: int
    ) -> float:
        """
        Calculate penalty for policy violations
        
        Args:
            severity: Violation severity (low, medium, high, critical)
            violation_count: Number of violations
            
        Returns:
            Penalty in credits
        """
        severity_penalties = {
            "low": 10.0,
            "medium": 50.0,
            "high": 100.0,
            "critical": 500.0
        }
        
        base_penalty = severity_penalties.get(severity, 20.0)
        
        # Escalating penalty for repeat violations
        escalation_factor = 1.0 + (violation_count * 0.5)
        
        return base_penalty * escalation_factor
    
    @staticmethod
    def get_pricing_summary(
        agent_id: str,
        tenant_id: str,
        db=None
    ) -> Dict[str, Any]:
        """
        Get pricing summary for agent
        
        Args:
            agent_id: Agent ID
            tenant_id: Tenant ID
            db: Optional database session (uses get_db() if not provided)
            
        Returns:
            Dictionary with pricing information
        """
        try:
            if db is None:
                db = next(get_db())
            asset_repo = AssetRepository(db)
            
            asset = asset_repo.get(agent_id)
            if not asset:
                return {
                    "agent_id": agent_id,
                    "registered": False
                }
            
            return {
                "agent_id": agent_id,
                "registered": True,
                "risk_tier": asset.risk_tier.value if asset.risk_tier else "unknown",
                "risk_multiplier": GovernanceEconomy.RISK_MULTIPLIERS.get(asset.risk_tier, 1.0),
                "compliance_status": asset.compliance_status.value if asset.compliance_status else "unknown",
                "compliance_reward": GovernanceEconomy.COMPLIANCE_REWARDS.get(asset.compliance_status, 0.0),
                "example_costs": {
                    "base_mission_100_credits": GovernanceEconomy.calculate_mission_cost(
                        100.0, agent_id, tenant_id, db=db
                    )["final_cost"],
                    "deployment_approval": GovernanceEconomy.calculate_approval_cost(
                        "deployment", asset.risk_tier
                    ) if asset.risk_tier else 50.0
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to get pricing summary: {e}")
            return {
                "agent_id": agent_id,
                "registered": False,
                "error": str(e)
            }


# Global instance
governance_economy = GovernanceEconomy()
