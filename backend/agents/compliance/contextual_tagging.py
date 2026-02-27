"""
Contextual Tagging Rule - Auto-tag assets based on usage context.

This module implements contextual tagging that automatically applies tags to assets
based on their usage patterns, data accessed, user roles, and deployment context.
Tags are used for risk assessment and regulatory compliance mapping.

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from enum import Enum

from .models import ComplianceResult


class TagCategory(str, Enum):
    """Categories of contextual tags."""
    DATA_SENSITIVITY = "data_sensitivity"
    DOMAIN = "domain"
    RISK_INDICATOR = "risk_indicator"
    COMPLIANCE = "compliance"


@dataclass
class ContextualTag:
    """
    A contextual tag applied to an asset based on usage context.
    
    Attributes:
        name: Tag name (e.g., "pii", "phi", "financial")
        category: Tag category
        applied_at: When tag was applied
        applied_by: Who/what applied the tag ("auto" or user_id)
        context: Context that triggered the tag
        confidence: Confidence score (0.0 to 1.0)
        expires_at: Optional expiration time for temporary tags
    """
    name: str
    category: TagCategory
    applied_at: datetime
    applied_by: str
    context: Dict[str, Any]
    confidence: float
    expires_at: Optional[datetime] = None
    
    def is_expired(self) -> bool:
        """Check if tag has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "name": self.name,
            "category": self.category.value,
            "applied_at": self.applied_at.isoformat(),
            "applied_by": self.applied_by,
            "context": self.context,
            "confidence": self.confidence,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass
class TagRule:
    """
    Rule for auto-tagging based on context patterns.
    
    Attributes:
        tag_name: Name of tag to apply
        category: Tag category
        risk_weight: Risk weight (0.0 to 1.0)
        conditions: List of conditions that must match
        confidence: Confidence score if conditions match
        ttl_hours: Time-to-live in hours (None for permanent)
    """
    tag_name: str
    category: TagCategory
    risk_weight: float
    conditions: List[Dict[str, Any]]
    confidence: float = 1.0
    ttl_hours: Optional[int] = None
    
    def matches(self, context: Dict[str, Any]) -> bool:
        """
        Check if context matches all conditions.
        
        Args:
            context: Context dictionary to check
            
        Returns:
            True if all conditions match
        """
        for condition in self.conditions:
            condition_type = condition.get("condition")
            
            if condition_type == "data_accessed":
                # Check if any pattern matches data accessed
                patterns = condition.get("patterns", [])
                data_accessed = context.get("data_accessed", [])
                if not any(pattern in str(data_accessed).lower() for pattern in patterns):
                    return False
            
            elif condition_type == "api_endpoint":
                # Check if API endpoint matches pattern
                patterns = condition.get("patterns", [])
                endpoint = context.get("api_endpoint", "")
                if not any(pattern in endpoint for pattern in patterns):
                    return False
            
            elif condition_type == "domain":
                # Check if domain matches
                value = condition.get("value")
                if context.get("domain") != value:
                    return False
            
            elif condition_type == "user_role":
                # Check if user role matches
                patterns = condition.get("patterns", [])
                user_role = context.get("user_role", "")
                if user_role not in patterns:
                    return False
            
            elif condition_type == "location":
                # Check if deployment location matches
                patterns = condition.get("patterns", [])
                location = context.get("location", "")
                if location not in patterns:
                    return False
            
            elif condition_type == "metadata":
                # Check if metadata field matches
                field = condition.get("field")
                value = condition.get("value")
                metadata = context.get("metadata", {})
                if metadata.get(field) != value:
                    return False
        
        return True


class ContextualTaggingRule:
    """
    Compliance rule that auto-tags assets based on usage context.
    
    This rule analyzes the context of asset usage (data accessed, user role,
    deployment location, etc.) and automatically applies relevant tags. Tags
    are used for risk assessment and regulatory compliance mapping.
    
    Example:
        rule = ContextualTaggingRule()
        context = {
            "asset_id": "medical-diagnosis-agent",
            "data_accessed": ["patient_records", "medical_images"],
            "user_role": "physician",
            "location": "production",
        }
        result = rule.check(context)
        # AIAsset tagged with ["phi", "healthcare", "high-risk", "hipaa"]
    """
    
    name = "contextual_tagging"
    description = "Auto-tag assets based on usage context"
    
    def __init__(self):
        """Initialize with default tag rules."""
        self.tag_rules = self._load_default_rules()
    
    def _load_default_rules(self) -> List[TagRule]:
        """
        Load default tagging rules.
        
        Returns:
            List of tag rules
        """
        return [
            # PII (Personally Identifiable Information)
            TagRule(
                tag_name="pii",
                category=TagCategory.DATA_SENSITIVITY,
                risk_weight=0.7,
                conditions=[
                    {
                        "condition": "data_accessed",
                        "patterns": ["email", "phone", "ssn", "address", "name", "user", "customer", "contact"],
                    }
                ],
            ),
            
            # PHI (Protected Health Information)
            TagRule(
                tag_name="phi",
                category=TagCategory.DATA_SENSITIVITY,
                risk_weight=0.8,
                conditions=[
                    {
                        "condition": "data_accessed",
                        "patterns": ["patient", "medical", "health", "diagnosis", "prescription", "treatment"],
                    }
                ],
            ),
            
            # Financial Data
            TagRule(
                tag_name="financial",
                category=TagCategory.DATA_SENSITIVITY,
                risk_weight=0.75,
                conditions=[
                    {
                        "condition": "data_accessed",
                        "patterns": ["credit_card", "bank_account", "transaction", "payment", "invoice", "financial"],
                    }
                ],
            ),
            
            # Biometric Data
            TagRule(
                tag_name="biometric",
                category=TagCategory.DATA_SENSITIVITY,
                risk_weight=0.85,
                conditions=[
                    {
                        "condition": "data_accessed",
                        "patterns": ["fingerprint", "facial_recognition", "iris_scan", "voice_print", "biometric"],
                    }
                ],
            ),
            
            # Healthcare Domain
            TagRule(
                tag_name="healthcare",
                category=TagCategory.DOMAIN,
                risk_weight=0.7,
                conditions=[
                    {
                        "condition": "domain",
                        "value": "healthcare",
                    }
                ],
            ),
            
            # Finance Domain
            TagRule(
                tag_name="finance",
                category=TagCategory.DOMAIN,
                risk_weight=0.7,
                conditions=[
                    {
                        "condition": "domain",
                        "value": "finance",
                    }
                ],
            ),
            
            # High Volume Risk Indicator
            TagRule(
                tag_name="high-volume",
                category=TagCategory.RISK_INDICATOR,
                risk_weight=0.5,
                conditions=[
                    {
                        "condition": "metadata",
                        "field": "volume",
                        "value": "high",
                    }
                ],
            ),
            
            # External API Risk Indicator
            TagRule(
                tag_name="external-api",
                category=TagCategory.RISK_INDICATOR,
                risk_weight=0.6,
                conditions=[
                    {
                        "condition": "metadata",
                        "field": "uses_external_api",
                        "value": True,
                    }
                ],
            ),
            
            # User-Facing Risk Indicator
            TagRule(
                tag_name="user-facing",
                category=TagCategory.RISK_INDICATOR,
                risk_weight=0.55,
                conditions=[
                    {
                        "condition": "location",
                        "patterns": ["production"],
                    }
                ],
            ),
            
            # Automated Decision Risk Indicator
            TagRule(
                tag_name="automated-decision",
                category=TagCategory.RISK_INDICATOR,
                risk_weight=0.7,
                conditions=[
                    {
                        "condition": "metadata",
                        "field": "makes_decisions",
                        "value": True,
                    }
                ],
            ),
            
            # GDPR Compliance Tag
            TagRule(
                tag_name="gdpr",
                category=TagCategory.COMPLIANCE,
                risk_weight=0.6,
                conditions=[
                    {
                        "condition": "data_accessed",
                        "patterns": ["email", "phone", "address", "name", "user", "customer"],
                    }
                ],
            ),
            
            # HIPAA Compliance Tag
            TagRule(
                tag_name="hipaa",
                category=TagCategory.COMPLIANCE,
                risk_weight=0.8,
                conditions=[
                    {
                        "condition": "data_accessed",
                        "patterns": ["patient", "medical", "health", "diagnosis"],
                    }
                ],
            ),
            
            # SOX Compliance Tag
            TagRule(
                tag_name="sox",
                category=TagCategory.COMPLIANCE,
                risk_weight=0.7,
                conditions=[
                    {
                        "condition": "data_accessed",
                        "patterns": ["financial", "transaction", "audit", "accounting"],
                    }
                ],
            ),
            
            # EU AI Act Compliance Tag
            TagRule(
                tag_name="eu-ai-act",
                category=TagCategory.COMPLIANCE,
                risk_weight=0.75,
                conditions=[
                    {
                        "condition": "metadata",
                        "field": "makes_decisions",
                        "value": True,
                    }
                ],
            ),
        ]
    
    def check(self, context: Dict[str, Any]) -> ComplianceResult:
        """
        Check context and apply relevant tags to asset.
        
        Args:
            context: Must contain:
                - asset_id: AIAsset identifier
                - data_accessed: List of data types/sources accessed (optional)
                - user_role: User role (optional)
                - location: Deployment location (optional)
                - domain: Business domain (optional)
                - metadata: Additional metadata (optional)
        
        Returns:
            ComplianceResult with tags applied
        """
        asset_id = context.get("asset_id")
        
        if not asset_id:
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason="Asset ID is required for contextual tagging"
            )
        
        # Find matching tags
        matched_tags = []
        for rule in self.tag_rules:
            if rule.matches(context):
                # Create contextual tag
                expires_at = None
                if rule.ttl_hours:
                    expires_at = datetime.utcnow() + timedelta(hours=rule.ttl_hours)
                
                tag = ContextualTag(
                    name=rule.tag_name,
                    category=rule.category,
                    applied_at=datetime.utcnow(),
                    applied_by="auto",
                    context=context,
                    confidence=rule.confidence,
                    expires_at=expires_at,
                )
                matched_tags.append(tag)
        
        if not matched_tags:
            return ComplianceResult(
                allowed=True,
                rule=self.name,
                reason=f"No contextual tags matched for asset '{asset_id}'"
            )
        
        # Apply tags to asset
        from ..registry.asset_registry import get_registry, AIAsset
        registry = get_registry()
        asset = registry.get(asset_id)
        
        if not asset:
            return ComplianceResult(
                allowed=False,
                rule=self.name,
                reason=f"Asset '{asset_id}' not found in registry"
            )
        
        # Update asset with contextual tags
        if not hasattr(asset, "contextual_tags"):
            asset.contextual_tags = {}
        
        for tag in matched_tags:
            asset.contextual_tags[tag.name] = tag
            # Also add to regular tags list for backward compatibility
            if tag.name not in asset.tags:
                asset.tags.append(tag.name)
        
        tag_names = [tag.name for tag in matched_tags]
        
        return ComplianceResult(
            allowed=True,
            rule=self.name,
            reason=f"Applied {len(matched_tags)} contextual tags to asset '{asset_id}': {', '.join(tag_names)}"
        )
    
    def add_rule(self, rule: TagRule) -> None:
        """
        Add a custom tagging rule.
        
        Args:
            rule: TagRule to add
        """
        self.tag_rules.append(rule)
    
    def remove_rule(self, tag_name: str) -> bool:
        """
        Remove a tagging rule by tag name.
        
        Args:
            tag_name: Name of tag rule to remove
            
        Returns:
            True if rule was removed
        """
        original_count = len(self.tag_rules)
        self.tag_rules = [r for r in self.tag_rules if r.tag_name != tag_name]
        return len(self.tag_rules) < original_count
    
    def get_tags_for_context(self, context: Dict[str, Any]) -> List[str]:
        """
        Get list of tags that would be applied for given context.
        
        Args:
            context: Context dictionary
            
        Returns:
            List of tag names that match
        """
        matched_tags = []
        for rule in self.tag_rules:
            if rule.matches(context):
                matched_tags.append(rule.tag_name)
        return matched_tags
