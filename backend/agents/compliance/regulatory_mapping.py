"""
Regulatory Mapping and Autonomous Authority Rules.

This module implements:
1. RegulatoryMappingRule: Maps asset tags to regulatory risk categories (EU AI Act)
2. AutonomousAuthorityRule: Enforces authority levels based on risk

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from .models import ComplianceResult


class RiskLevel(str, Enum):
    """EU AI Act risk levels."""
    UNACCEPTABLE = "unacceptable"
    HIGH = "high"
    LIMITED = "limited"
    MINIMAL = "minimal"


class AuthorityLevel(int, Enum):
    """User authority levels for risk-based access control."""
    GUEST = 0
    USER = 1
    OPERATOR = 2
    ADMIN = 3
    COMPLIANCE_OFFICER = 4


@dataclass
class RiskAssessment:
    """
    Risk assessment for an asset based on regulatory mapping.
    
    Attributes:
        risk_level: EU AI Act risk level
        regulation: Applicable regulation
        requirements: List of compliance requirements
        assessed_at: Assessment timestamp
        assessed_by: Who performed assessment
        valid_until: Optional expiration
        notes: Additional notes
    """
    risk_level: RiskLevel
    regulation: str
    requirements: List[str]
    assessed_at: datetime
    assessed_by: str
    valid_until: Optional[datetime] = None
    notes: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "risk_level": self.risk_level.value,
            "regulation": self.regulation,
            "requirements": self.requirements,
            "assessed_at": self.assessed_at.isoformat(),
            "assessed_by": self.assessed_by,
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "notes": self.notes,
        }


@dataclass
class RiskMapping:
    """
    Mapping from tags to risk levels and requirements.
    
    Attributes:
        risk_level: Risk level for this mapping
        tags: Tags that trigger this risk level
        requirements: Compliance requirements
        action: Action to take (allow, block, require_oversight)
    """
    risk_level: RiskLevel
    tags: List[str]
    requirements: List[str]
    action: str = "allow"


class RegulatoryMappingRule:
    """
    Compliance rule that maps asset tags to regulatory risk categories.
    
    This rule analyzes asset tags (from ContextualTaggingRule) and maps them
    to EU AI Act risk levels, generating appropriate compliance requirements.
    
    Risk Levels:
    - Unacceptable: Prohibited AI systems (blocked)
    - High: Significant risk to safety/rights (strict requirements)
    - Limited: Transparency obligations
    - Minimal: Low/no risk (no special requirements)
    
    Example:
        rule = RegulatoryMappingRule()
        context = {
            "asset_id": "medical-diagnosis-agent",
            "tags": ["phi", "healthcare", "automated-decision"],
        }
        result = rule.check(context)
        # Result: risk_level="high", requirements=[human-oversight, ...]
    """
    
    name = "regulatory_mapping"
    description = "Map asset tags to EU AI Act risk categories"
    
    def __init__(self):
        """Initialize with EU AI Act risk mappings."""
        self.risk_mappings = self._load_eu_ai_act_mappings()
    
    def _load_eu_ai_act_mappings(self) -> List[RiskMapping]:
        """
        Load EU AI Act risk mappings.
        
        Returns:
            List of risk mappings
        """
        return [
            # Unacceptable Risk - Prohibited
            RiskMapping(
                risk_level=RiskLevel.UNACCEPTABLE,
                tags=[
                    "social-scoring",
                    "subliminal-manipulation",
                    "real-time-biometric-public",
                    "exploit-vulnerabilities",
                ],
                requirements=[],
                action="block",
            ),
            
            # High Risk - Strict Requirements
            RiskMapping(
                risk_level=RiskLevel.HIGH,
                tags=[
                    "medical-diagnosis",
                    "credit-scoring",
                    "hiring",
                    "law-enforcement",
                    "critical-infrastructure",
                    "education-assessment",
                    "employment-management",
                    "essential-services",
                    "biometric",
                ],
                requirements=[
                    "human-oversight",
                    "risk-assessment",
                    "technical-documentation",
                    "accuracy-testing",
                    "data-governance",
                    "transparency",
                    "cybersecurity",
                    "quality-management",
                ],
                action="require_oversight",
            ),
            
            # Limited Risk - Transparency
            RiskMapping(
                risk_level=RiskLevel.LIMITED,
                tags=[
                    "chatbot",
                    "emotion-recognition",
                    "deepfake",
                    "content-generation",
                ],
                requirements=[
                    "transparency-disclosure",
                    "user-notification",
                ],
                action="allow",
            ),
            
            # Minimal Risk - No Special Requirements
            RiskMapping(
                risk_level=RiskLevel.MINIMAL,
                tags=[
                    "spam-filter",
                    "content-recommendation",
                    "general",
                ],
                requirements=[],
                action="allow",
            ),
        ]
    
    def _determine_risk_level(self, tags: List[str]) -> tuple[RiskLevel, List[str], str]:
        """
        Determine risk level based on tags.
        
        Args:
            tags: List of asset tags
            
        Returns:
            Tuple of (risk_level, requirements, action)
        """
        # Check for unacceptable risk first
        for mapping in self.risk_mappings:
            if mapping.risk_level == RiskLevel.UNACCEPTABLE:
                if any(tag in tags for tag in mapping.tags):
                    return mapping.risk_level, mapping.requirements, mapping.action
        
        # Check for high risk
        for mapping in self.risk_mappings:
            if mapping.risk_level == RiskLevel.HIGH:
                if any(tag in tags for tag in mapping.tags):
                    return mapping.risk_level, mapping.requirements, mapping.action
        
        # Check for limited risk
        for mapping in self.risk_mappings:
            if mapping.risk_level == RiskLevel.LIMITED:
                if any(tag in tags for tag in mapping.tags):
                    return mapping.risk_level, mapping.requirements, mapping.action
        
        # Default to minimal risk
        return RiskLevel.MINIMAL, [], "allow"
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check asset tags and map to risk level.
        
        Args:
            context: Must contain:
                - asset_id: Asset identifier
                - tags: List of asset tags (optional, will fetch from registry)
        
        Returns:
            ComplianceResult with risk assessment
        """
        asset_id = context.get("asset_id")
        
        if not asset_id:
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason="Asset ID is required for regulatory mapping"
            )
        
        # Get tags from context or registry
        tags = context.get("tags")
        if not tags:
            from ..registry.asset_registry import get_registry
            registry = get_registry()
            asset = registry.get(asset_id)
            
            if not asset:
                return ComplianceResult(
                    allowed=False,
                    rule=self.name,
                    reason=f"Asset '{asset_id}' not found in registry"
                )
            
            tags = asset.tags
        
        # Determine risk level
        risk_level, requirements, action = self._determine_risk_level(tags)
        
        # Create risk assessment
        assessment = RiskAssessment(
            risk_level=risk_level,
            regulation="EU AI Act",
            requirements=requirements,
            assessed_at=datetime.utcnow(),
            assessed_by="auto",
            notes=f"Risk level determined based on tags: {', '.join(tags)}",
        )
        
        # Store assessment in asset
        from ..registry.asset_registry import get_registry
        registry = get_registry()
        asset = registry.get(asset_id)
        
        if asset:
            if not hasattr(asset, "risk_assessment"):
                asset.risk_assessment = None
            asset.risk_assessment = assessment
        
        # Check if action is block
        if action == "block":
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason=f"Asset '{asset_id}' has unacceptable risk level and is prohibited under EU AI Act"
            )
        
        # Build reason message
        if requirements:
            req_list = ", ".join(requirements)
            reason = f"Asset '{asset_id}' mapped to {risk_level.value} risk. Requirements: {req_list}"
        else:
            reason = f"Asset '{asset_id}' mapped to {risk_level.value} risk with no special requirements"
        
        return ComplianceResult(
            allowed=True,
            rule=self.name,
            reason=reason
        )
    
    def add_mapping(self, mapping: RiskMapping) -> None:
        """
        Add custom risk mapping.
        
        Args:
            mapping: RiskMapping to add
        """
        self.risk_mappings.append(mapping)
    
    def get_risk_level(self, tags: List[str]) -> RiskLevel:
        """
        Get risk level for given tags.
        
        Args:
            tags: List of tags
            
        Returns:
            Risk level
        """
        risk_level, _, _ = self._determine_risk_level(tags)
        return risk_level


class AutonomousAuthorityRule:
    """
    Compliance rule that enforces authority levels based on risk.
    
    This rule checks if a user has sufficient authority to use an asset
    based on its risk level. Higher risk assets require higher authority.
    
    Authority Levels:
    - 0 (Guest): Minimal risk only
    - 1 (User): Minimal, Limited risk
    - 2 (Operator): Minimal, Limited, High (with oversight)
    - 3 (Admin): All except Unacceptable
    - 4 (Compliance Officer): All (override)
    
    Example:
        rule = AutonomousAuthorityRule()
        context = {
            "user_id": "physician-001",
            "user_authority_level": 2,  # Operator
            "asset_id": "medical-diagnosis-agent",
            "asset_risk_level": "high",
            "human_oversight": True,
        }
        result = rule.check(context)
        # Result: allowed=True (Operator with oversight can use high-risk)
    """
    
    name = "autonomous_authority"
    description = "Enforce authority levels based on risk"
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check if user has authority to use asset.
        
        Args:
            context: Must contain:
                - user_id: User identifier
                - user_authority_level: User authority level (0-4)
                - asset_id: Asset identifier
                - asset_risk_level: Asset risk level (optional, will fetch)
                - human_oversight: Whether human oversight is available (optional)
        
        Returns:
            ComplianceResult indicating if access is allowed
        """
        user_id = context.get("user_id")
        user_level = context.get("user_authority_level")
        asset_id = context.get("asset_id")
        
        if not user_id:
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason="User ID is required for authority check"
            )
        
        if user_level is None:
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason="User authority level is required"
            )
        
        if not asset_id:
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason="Asset ID is required for authority check"
            )
        
        # Get asset risk level
        risk_level_str = context.get("asset_risk_level")
        if not risk_level_str:
            # Fetch from asset
            from ..registry.asset_registry import get_registry
            registry = get_registry()
            asset = registry.get(asset_id)
            
            if not asset:
                return ComplianceResult(
                    allowed=False,
                    rule=self.name,
                    reason=f"Asset '{asset_id}' not found in registry"
                )
            
            if hasattr(asset, "risk_assessment") and asset.risk_assessment:
                risk_level_str = asset.risk_assessment.risk_level.value
            else:
                # No risk assessment, default to minimal
                risk_level_str = "minimal"
        
        # Parse risk level
        try:
            risk_level = RiskLevel(risk_level_str)
        except ValueError:
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason=f"Invalid risk level: {risk_level_str}"
            )
        
        # Check oversight
        has_oversight = context.get("human_oversight", False)
        
        # Apply authority rules
        allowed = self._check_authority(user_level, risk_level, has_oversight)
        
        if not allowed:
            if risk_level == RiskLevel.UNACCEPTABLE:
                reason = f"User '{user_id}' (level {user_level}) cannot access unacceptable risk asset '{asset_id}'. Only Compliance Officers (level 4) can override."
            elif risk_level == RiskLevel.HIGH and not has_oversight:
                reason = f"User '{user_id}' (level {user_level}) cannot access high-risk asset '{asset_id}' without human oversight. Requires Admin (level 3) or Operator (level 2) with oversight."
            elif risk_level == RiskLevel.HIGH and has_oversight:
                reason = f"User '{user_id}' (level {user_level}) cannot access high-risk asset '{asset_id}'. Requires Operator (level 2) or higher with oversight."
            elif risk_level == RiskLevel.LIMITED:
                reason = f"User '{user_id}' (level {user_level}) cannot access limited-risk asset '{asset_id}'. Requires User (level 1) or higher."
            else:
                reason = f"User '{user_id}' (level {user_level}) does not have sufficient authority for {risk_level.value} risk asset '{asset_id}'"
            
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason=reason
            )
        
        # Access allowed
        oversight_note = " with human oversight" if has_oversight and risk_level == RiskLevel.HIGH else ""
        reason = f"User '{user_id}' (level {user_level}) authorized to access {risk_level.value} risk asset '{asset_id}'{oversight_note}"
        
        return ComplianceResult(
            allowed=True,
            rule=self.name,
            reason=reason
        )
    
    def _check_authority(self, user_level: int, risk_level: RiskLevel, has_oversight: bool) -> bool:
        """
        Check if user level is sufficient for risk level.
        
        Args:
            user_level: User authority level (0-4)
            risk_level: Asset risk level
            has_oversight: Whether human oversight is available
            
        Returns:
            True if access is allowed
        """
        # Compliance Officer can access everything
        if user_level >= AuthorityLevel.COMPLIANCE_OFFICER:
            return True
        
        # Unacceptable risk requires Compliance Officer
        if risk_level == RiskLevel.UNACCEPTABLE:
            return False
        
        # High risk requires Admin or Operator with oversight
        if risk_level == RiskLevel.HIGH:
            if user_level >= AuthorityLevel.ADMIN:
                return True
            if user_level >= AuthorityLevel.OPERATOR and has_oversight:
                return True
            return False
        
        # Limited risk requires User or higher
        if risk_level == RiskLevel.LIMITED:
            return user_level >= AuthorityLevel.USER
        
        # Minimal risk allows all users
        return True
