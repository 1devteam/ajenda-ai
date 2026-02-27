"""
Risk Scoring Engine for Omnipath V2.

This module implements quantitative risk scoring based on multiple weighted factors:
1. Inherent Risk (40%): EU AI Act risk level
2. Data Sensitivity (25%): Tags (PHI, PII, financial, biometric)
3. Operational Context (20%): Production, user-facing, automated decisions
4. Historical Risk (15%): Past incidents with time decay

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from .regulatory_mapping import RiskLevel
from ..registry.asset_registry import get_registry, AIAsset
from ..registry.lineage_tracker import get_tracker


class RiskFactor(str, Enum):
    """Risk factor categories for scoring."""
    INHERENT = "inherent"
    DATA_SENSITIVITY = "data_sensitivity"
    OPERATIONAL_CONTEXT = "operational_context"
    HISTORICAL = "historical"


class RiskTier(str, Enum):
    """Risk tiers based on calculated score."""
    CRITICAL = "critical"      # 80-100: C-Level approval required
    HIGH = "high"              # 60-79: Compliance Officer approval required
    MEDIUM = "medium"          # 40-59: Admin approval required
    LOW = "low"                # 20-39: Operator approval required
    MINIMAL = "minimal"        # 0-19: Auto-approved


@dataclass
class RiskScore:
    """
    Calculated risk score for an asset.
    
    Attributes:
        asset_id: AIAsset identifier
        score: Calculated risk score (0-100)
        tier: Risk tier based on score
        breakdown: Score breakdown by factor
        calculated_at: When score was calculated
        calculated_by: Who/what calculated the score
        expires_at: Optional expiration time
        notes: Additional notes
    """
    asset_id: str
    score: float  # 0-100
    tier: RiskTier
    breakdown: Dict[RiskFactor, float]
    calculated_at: datetime
    calculated_by: str
    expires_at: Optional[datetime] = None
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "asset_id": self.asset_id,
            "score": self.score,
            "tier": self.tier.value,
            "breakdown": {k.value: v for k, v in self.breakdown.items()},
            "calculated_at": self.calculated_at.isoformat(),
            "calculated_by": self.calculated_by,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "notes": self.notes,
        }


class RiskScoringEngine:
    """
    Singleton that calculates quantitative risk scores for assets.
    
    The engine uses a weighted formula:
        risk_score = (
            inherent_risk * 0.40 +
            data_sensitivity * 0.25 +
            operational_context * 0.20 +
            historical_risk * 0.15
        )
    
    Example:
        engine = get_risk_scoring_engine()
        risk_score = engine.calculate_risk_score("medical-agent-001")
        
        if risk_score.tier == RiskTier.CRITICAL:
            print(f"Critical risk: {risk_score.score}")
            print(f"Breakdown: {risk_score.breakdown}")
    """
    
    _instance: Optional["RiskScoringEngine"] = None
    
    # Weight factors
    INHERENT_WEIGHT = 0.40
    DATA_SENSITIVITY_WEIGHT = 0.25
    OPERATIONAL_CONTEXT_WEIGHT = 0.20
    HISTORICAL_WEIGHT = 0.15
    
    # Inherent risk scores by EU AI Act level
    INHERENT_SCORES = {
        RiskLevel.UNACCEPTABLE: 100,
        RiskLevel.HIGH: 75,
        RiskLevel.LIMITED: 40,
        RiskLevel.MINIMAL: 10,
    }
    
    # Data sensitivity scores by tag
    DATA_SENSITIVITY_SCORES = {
        "phi": 25,
        "biometric": 25,
        "pii": 20,
        "financial": 20,
        "sensitive": 15,
    }
    
    # Operational context scores
    OPERATIONAL_SCORES = {
        "production": 20,
        "user-facing": 15,
        "automated-decision": 20,
        "external-api": 15,
        "high-volume": 10,
        "staging": 10,
        "development": 5,
    }
    
    # Incident severity scores
    INCIDENT_SCORES = {
        "critical": 30,
        "major": 20,
        "minor": 10,
    }
    
    # Time decay for historical incidents (days)
    INCIDENT_DECAY_DAYS = 90
    INCIDENT_DECAY_FACTOR = 0.5
    
    def __new__(cls):
        """Ensure singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize risk scoring engine."""
        self.registry = get_registry()
        self.lineage_tracker = get_tracker()
    
    def calculate_risk_score(self, asset_id: str) -> RiskScore:
        """
        Calculate comprehensive risk score for an asset.
        
        Args:
            asset_id: AIAsset identifier
            
        Returns:
            RiskScore with calculated score and breakdown
            
        Raises:
            ValueError: If asset not found
        """
        # Get asset
        asset = self.registry.get(asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found in registry")
        
        # Calculate each factor
        inherent = self._calculate_inherent_risk(asset)
        data_sensitivity = self._calculate_data_sensitivity(asset)
        operational = self._calculate_operational_context(asset)
        historical = self._calculate_historical_risk(asset)
        
        # Weighted sum
        score = (
            inherent * self.INHERENT_WEIGHT +
            data_sensitivity * self.DATA_SENSITIVITY_WEIGHT +
            operational * self.OPERATIONAL_CONTEXT_WEIGHT +
            historical * self.HISTORICAL_WEIGHT
        )
        
        # Normalize to 0-100
        score = min(100.0, max(0.0, score))
        
        # Determine tier
        tier = self.get_risk_tier(score)
        
        # Build breakdown
        breakdown = {
            RiskFactor.INHERENT: inherent,
            RiskFactor.DATA_SENSITIVITY: data_sensitivity,
            RiskFactor.OPERATIONAL_CONTEXT: operational,
            RiskFactor.HISTORICAL: historical,
        }
        
        # Create risk score
        risk_score = RiskScore(
            asset_id=asset_id,
            score=score,
            tier=tier,
            breakdown=breakdown,
            calculated_at=datetime.utcnow(),
            calculated_by="risk_scoring_engine",
            expires_at=datetime.utcnow() + timedelta(days=30),  # 30-day validity
        )
        
        # Store in asset metadata
        if not hasattr(asset, "risk_score"):
            asset.risk_score = risk_score
        else:
            asset.risk_score = risk_score
        
        return risk_score
    
    def _calculate_inherent_risk(self, asset) -> float:
        """Calculate inherent risk from EU AI Act level."""
        # Check if asset has risk assessment from RegulatoryMappingRule
        if hasattr(asset, "risk_assessment") and asset.risk_assessment:
            risk_level = asset.risk_assessment.risk_level
            return self.INHERENT_SCORES.get(risk_level, 10)
        
        # Default to minimal if not assessed
        return self.INHERENT_SCORES[RiskLevel.MINIMAL]
    
    def _calculate_data_sensitivity(self, asset) -> float:
        """Calculate data sensitivity score from tags."""
        if not asset.tags:
            return 0.0
        
        score = 0.0
        for tag in asset.tags:
            tag_lower = tag.lower()
            if tag_lower in self.DATA_SENSITIVITY_SCORES:
                score += self.DATA_SENSITIVITY_SCORES[tag_lower]
        
        # Cap at 100
        return min(100.0, score)
    
    def _calculate_operational_context(self, asset) -> float:
        """Calculate operational context score from tags and metadata."""
        score = 0.0
        
        # Check tags
        if asset.tags:
            for tag in asset.tags:
                tag_lower = tag.lower()
                if tag_lower in self.OPERATIONAL_SCORES:
                    score += self.OPERATIONAL_SCORES[tag_lower]
        
        # Check metadata for additional context
        if hasattr(asset, "metadata") and asset.metadata:
            # Check deployment location
            location = asset.metadata.get("location", "").lower()
            if location in self.OPERATIONAL_SCORES:
                score += self.OPERATIONAL_SCORES[location]
            
            # Check if makes decisions
            if asset.metadata.get("makes_decisions"):
                score += self.OPERATIONAL_SCORES["automated-decision"]
            
            # Check if user-facing
            if asset.metadata.get("user_facing"):
                score += self.OPERATIONAL_SCORES["user-facing"]
        
        # Cap at 100
        return min(100.0, score)
    
    def _calculate_historical_risk(self, asset) -> float:
        """Calculate historical risk from past incidents with time decay."""
        # Get lineage events
        events = self.lineage_tracker.get_events_for_asset(asset.asset_id)
        
        if not events:
            return 0.0
        
        score = 0.0
        now = datetime.utcnow()
        
        for event in events:
            # Check if event is an incident
            event_type = event.get("event_type", "").lower()
            if "incident" not in event_type:
                continue
            
            # Get severity from metadata
            metadata = event.get("metadata", {})
            severity = metadata.get("severity", "minor").lower()
            
            # Base score for severity
            incident_score = self.INCIDENT_SCORES.get(severity, 10)
            
            # Apply time decay
            event_time = event.get("timestamp", now)
            if isinstance(event_time, str):
                event_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
            
            days_old = (now - event_time).days
            if days_old > self.INCIDENT_DECAY_DAYS:
                incident_score *= self.INCIDENT_DECAY_FACTOR
            
            score += incident_score
        
        # Cap at 100
        return min(100.0, score)
    
    def get_risk_tier(self, score: float) -> RiskTier:
        """
        Determine risk tier from score.
        
        Args:
            score: Risk score (0-100)
            
        Returns:
            RiskTier
        """
        if score >= 80:
            return RiskTier.CRITICAL
        elif score >= 60:
            return RiskTier.HIGH
        elif score >= 40:
            return RiskTier.MEDIUM
        elif score >= 20:
            return RiskTier.LOW
        else:
            return RiskTier.MINIMAL
    
    def get_risk_breakdown(self, asset_id: str) -> Dict[RiskFactor, float]:
        """
        Get detailed risk breakdown for an asset.
        
        Args:
            asset_id: AIAsset identifier
            
        Returns:
            Dictionary mapping risk factors to scores
        """
        risk_score = self.calculate_risk_score(asset_id)
        return risk_score.breakdown
    
    def recalculate_all_scores(self) -> List[RiskScore]:
        """
        Recalculate risk scores for all assets.
        
        Returns:
            List of updated risk scores
        """
        scores = []
        assets = self.registry.list_all()
        
        for asset in assets:
            try:
                score = self.calculate_risk_score(asset.asset_id)
                scores.append(score)
            except Exception as e:
                # Log error but continue
                print(f"Error calculating risk for {asset.asset_id}: {e}")
        
        return scores
    
    def get_score(self, asset_id: str) -> Optional[RiskScore]:
        """
        Get current risk score for an asset (from cache if available).
        
        Args:
            asset_id: AIAsset identifier
            
        Returns:
            RiskScore if available, None otherwise
        """
        asset = self.registry.get(asset_id)
        if not asset:
            return None
        
        # Check if asset has cached score
        if hasattr(asset, "risk_score") and asset.risk_score:
            # Check if expired
            if asset.risk_score.expires_at and asset.risk_score.expires_at < datetime.utcnow():
                # Recalculate
                return self.calculate_risk_score(asset_id)
            return asset.risk_score
        
        # Calculate new score
        return self.calculate_risk_score(asset_id)


# Singleton accessor
_engine_instance: Optional[RiskScoringEngine] = None


def get_risk_scoring_engine() -> RiskScoringEngine:
    """Get the singleton risk scoring engine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RiskScoringEngine()
    return _engine_instance
