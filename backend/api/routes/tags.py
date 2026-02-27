"""
Tags API - Contextual tagging and risk assessment endpoints.

This module provides REST API endpoints for:
- Tag definition management
- Asset tagging operations
- Tag analysis and reporting
- Risk assessment queries

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.agents.registry.asset_registry import get_registry, AssetType, AssetStatus
from backend.agents.compliance.contextual_tagging import (
    ContextualTag,
    ContextualTaggingRule,
    TagCategory,
    TagRule,
)
from backend.agents.compliance.regulatory_mapping import (
    RegulatoryMappingRule,
    AutonomousAuthorityRule,
    RiskLevel,
    RiskAssessment,
)


router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


class TagDefinitionCreate(BaseModel):
    """Request model for creating tag definition."""
    name: str = Field(..., description="Tag name")
    category: str = Field(..., description="Tag category")
    risk_weight: float = Field(..., ge=0.0, le=1.0, description="Risk weight (0.0-1.0)")
    conditions: List[Dict[str, Any]] = Field(..., description="Auto-tagging conditions")
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Confidence score")
    ttl_hours: Optional[int] = Field(None, description="Time-to-live in hours")


class TagDefinitionResponse(BaseModel):
    """Response model for tag definition."""
    name: str
    category: str
    risk_weight: float
    conditions: List[Dict[str, Any]]
    confidence: float
    ttl_hours: Optional[int]


class ApplyTagsRequest(BaseModel):
    """Request model for applying tags to asset."""
    context: Dict[str, Any] = Field(..., description="Context for auto-tagging")


class ApplyTagsResponse(BaseModel):
    """Response model for tag application."""
    asset_id: str
    tags_applied: List[str]
    tags_total: int
    message: str


class TagHistoryResponse(BaseModel):
    """Response model for tag history."""
    name: str
    category: str
    applied_at: str
    applied_by: str
    context: Dict[str, Any]
    confidence: float
    expires_at: Optional[str]


class RiskAssessmentResponse(BaseModel):
    """Response model for risk assessment."""
    asset_id: str
    risk_level: str
    regulation: str
    requirements: List[str]
    assessed_at: str
    assessed_by: str
    notes: str


class AuthorityCheckRequest(BaseModel):
    """Request model for authority check."""
    user_id: str
    user_authority_level: int = Field(..., ge=0, le=4)
    asset_id: str
    human_oversight: bool = False


class AuthorityCheckResponse(BaseModel):
    """Response model for authority check."""
    allowed: bool
    user_id: str
    user_authority_level: int
    asset_id: str
    asset_risk_level: str
    reason: str


class TagStatsResponse(BaseModel):
    """Response model for tag statistics."""
    total_tags: int
    tags_by_category: Dict[str, int]
    most_common_tags: List[Dict[str, Any]]
    assets_by_risk_level: Dict[str, int]


# ============================================================================
# TAG DEFINITION ENDPOINTS
# ============================================================================


@router.post("/definitions", response_model=TagDefinitionResponse, status_code=201)
async def create_tag_definition(definition: TagDefinitionCreate):
    """
    Create a new tag definition.
    
    Tag definitions control how assets are automatically tagged based on context.
    """
    try:
        # Validate category
        try:
            category = TagCategory(definition.category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {[c.value for c in TagCategory]}"
            )
        
        # Create tag rule
        rule = TagRule(
            tag_name=definition.name,
            category=category,
            risk_weight=definition.risk_weight,
            conditions=definition.conditions,
            confidence=definition.confidence,
            ttl_hours=definition.ttl_hours,
        )
        
        # Add to tagging rule engine
        tagging_rule = ContextualTaggingRule()
        tagging_rule.add_rule(rule)
        
        return TagDefinitionResponse(
            name=definition.name,
            category=definition.category,
            risk_weight=definition.risk_weight,
            conditions=definition.conditions,
            confidence=definition.confidence,
            ttl_hours=definition.ttl_hours,
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/definitions", response_model=List[TagDefinitionResponse])
async def list_tag_definitions():
    """
    List all tag definitions.
    
    Returns all configured tag rules used for auto-tagging.
    """
    try:
        tagging_rule = ContextualTaggingRule()
        
        definitions = []
        for rule in tagging_rule.tag_rules:
            definitions.append(TagDefinitionResponse(
                name=rule.tag_name,
                category=rule.category.value,
                risk_weight=rule.risk_weight,
                conditions=rule.conditions,
                confidence=rule.confidence,
                ttl_hours=rule.ttl_hours,
            ))
        
        return definitions
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/definitions/{name}", response_model=TagDefinitionResponse)
async def get_tag_definition(name: str):
    """
    Get a specific tag definition by name.
    """
    try:
        tagging_rule = ContextualTaggingRule()
        
        for rule in tagging_rule.tag_rules:
            if rule.tag_name == name:
                return TagDefinitionResponse(
                    name=rule.tag_name,
                    category=rule.category.value,
                    risk_weight=rule.risk_weight,
                    conditions=rule.conditions,
                    confidence=rule.confidence,
                    ttl_hours=rule.ttl_hours,
                )
        
        raise HTTPException(status_code=404, detail=f"Tag definition '{name}' not found")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/definitions/{name}", status_code=204)
async def delete_tag_definition(name: str):
    """
    Delete a tag definition.
    
    Note: This only removes the auto-tagging rule, not existing tags on assets.
    """
    try:
        tagging_rule = ContextualTaggingRule()
        
        if not tagging_rule.remove_rule(name):
            raise HTTPException(status_code=404, detail=f"Tag definition '{name}' not found")
        
        return None
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ASSET TAGGING ENDPOINTS
# ============================================================================


@router.post("/assets/{asset_id}/apply", response_model=ApplyTagsResponse)
async def apply_tags_to_asset(asset_id: str, request: ApplyTagsRequest):
    """
    Apply contextual tags to an asset based on usage context.
    
    Analyzes the provided context and automatically applies relevant tags.
    """
    try:
        # Add asset_id to context
        context = request.context.copy()
        context["asset_id"] = asset_id
        
        # Apply contextual tagging
        tagging_rule = ContextualTaggingRule()
        result = tagging_rule.check(context)
        
        if not result.allowed:
            raise HTTPException(status_code=400, detail=result.reason)
        
        # Get updated asset
        registry = get_registry()
        asset = registry.get(asset_id)
        
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
        
        # Get applied tags
        tags_applied = []
        if hasattr(asset, "contextual_tags"):
            tags_applied = list(asset.contextual_tags.keys())
        
        return ApplyTagsResponse(
            asset_id=asset_id,
            tags_applied=tags_applied,
            tags_total=len(asset.tags),
            message=result.reason,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assets/{asset_id}/tags", response_model=List[TagHistoryResponse])
async def get_asset_tags(asset_id: str):
    """
    Get all contextual tags for an asset with history.
    """
    try:
        registry = get_registry()
        asset = registry.get(asset_id)
        
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
        
        if not hasattr(asset, "contextual_tags") or not asset.contextual_tags:
            return []
        
        tags = []
        for tag in asset.contextual_tags.values():
            tags.append(TagHistoryResponse(
                name=tag.name,
                category=tag.category.value,
                applied_at=tag.applied_at.isoformat(),
                applied_by=tag.applied_by,
                context=tag.context,
                confidence=tag.confidence,
                expires_at=tag.expires_at.isoformat() if tag.expires_at else None,
            ))
        
        return tags
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/assets/{asset_id}/tags/{tag_name}", status_code=204)
async def remove_tag_from_asset(asset_id: str, tag_name: str):
    """
    Remove a specific tag from an asset.
    """
    try:
        registry = get_registry()
        asset = registry.get(asset_id)
        
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
        
        # Remove from contextual tags
        if hasattr(asset, "contextual_tags") and tag_name in asset.contextual_tags:
            del asset.contextual_tags[tag_name]
        
        # Remove from regular tags
        if tag_name in asset.tags:
            asset.tags.remove(tag_name)
        
        return None
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RISK ASSESSMENT ENDPOINTS
# ============================================================================


@router.post("/assets/{asset_id}/assess-risk", response_model=RiskAssessmentResponse)
async def assess_asset_risk(asset_id: str):
    """
    Assess risk level for an asset based on its tags.
    
    Maps asset tags to EU AI Act risk categories and generates compliance requirements.
    """
    try:
        registry = get_registry()
        asset = registry.get(asset_id)
        
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
        
        # Apply regulatory mapping
        mapping_rule = RegulatoryMappingRule()
        context = {
            "asset_id": asset_id,
            "tags": asset.tags,
        }
        result = mapping_rule.check(context)
        
        if not result.allowed:
            raise HTTPException(status_code=400, detail=result.reason)
        
        # Get risk assessment
        if not hasattr(asset, "risk_assessment") or not asset.risk_assessment:
            raise HTTPException(status_code=500, detail="Risk assessment failed")
        
        assessment = asset.risk_assessment
        
        return RiskAssessmentResponse(
            asset_id=asset_id,
            risk_level=assessment.risk_level.value,
            regulation=assessment.regulation,
            requirements=assessment.requirements,
            assessed_at=assessment.assessed_at.isoformat(),
            assessed_by=assessment.assessed_by,
            notes=assessment.notes,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/assets/{asset_id}/risk", response_model=RiskAssessmentResponse)
async def get_asset_risk(asset_id: str):
    """
    Get current risk assessment for an asset.
    """
    try:
        registry = get_registry()
        asset = registry.get(asset_id)
        
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found")
        
        if not hasattr(asset, "risk_assessment") or not asset.risk_assessment:
            raise HTTPException(status_code=404, detail=f"No risk assessment found for asset '{asset_id}'")
        
        assessment = asset.risk_assessment
        
        return RiskAssessmentResponse(
            asset_id=asset_id,
            risk_level=assessment.risk_level.value,
            regulation=assessment.regulation,
            requirements=assessment.requirements,
            assessed_at=assessment.assessed_at.isoformat(),
            assessed_by=assessment.assessed_by,
            notes=assessment.notes,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# AUTHORITY CHECK ENDPOINTS
# ============================================================================


@router.post("/authority/check", response_model=AuthorityCheckResponse)
async def check_user_authority(request: AuthorityCheckRequest):
    """
    Check if user has authority to access an asset based on risk level.
    
    Enforces risk-based access control using authority levels.
    """
    try:
        registry = get_registry()
        asset = registry.get(request.asset_id)
        
        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset '{request.asset_id}' not found")
        
        # Get asset risk level
        asset_risk_level = "minimal"
        if hasattr(asset, "risk_assessment") and asset.risk_assessment:
            asset_risk_level = asset.risk_assessment.risk_level.value
        
        # Check authority
        authority_rule = AutonomousAuthorityRule()
        context = {
            "user_id": request.user_id,
            "user_authority_level": request.user_authority_level,
            "asset_id": request.asset_id,
            "asset_risk_level": asset_risk_level,
            "human_oversight": request.human_oversight,
        }
        result = authority_rule.check(context)
        
        return AuthorityCheckResponse(
            allowed=result.allowed,
            user_id=request.user_id,
            user_authority_level=request.user_authority_level,
            asset_id=request.asset_id,
            asset_risk_level=asset_risk_level,
            reason=result.reason,
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# TAG ANALYSIS ENDPOINTS
# ============================================================================


@router.get("/analysis/by-tag/{tag_name}")
async def get_assets_by_tag(tag_name: str):
    """
    Get all assets that have a specific tag.
    """
    try:
        registry = get_registry()
        all_assets = registry.list_all()
        
        matching_assets = []
        for asset in all_assets:
            if tag_name in asset.tags:
                matching_assets.append({
                    "asset_id": asset.asset_id,
                    "name": asset.name,
                    "type": asset.asset_type.value,
                    "owner": asset.owner,
                    "status": asset.status.value,
                })
        
        return {
            "tag_name": tag_name,
            "asset_count": len(matching_assets),
            "assets": matching_assets,
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analysis/stats", response_model=TagStatsResponse)
async def get_tag_statistics():
    """
    Get overall tag usage statistics.
    """
    try:
        registry = get_registry()
        all_assets = registry.list_all()
        
        # Count tags by category
        tags_by_category = {}
        tag_counts = {}
        risk_level_counts = {
            "minimal": 0,
            "limited": 0,
            "high": 0,
            "unacceptable": 0,
        }
        
        for asset in all_assets:
            # Count regular tags
            for tag in asset.tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            
            # Count contextual tags by category
            if hasattr(asset, "contextual_tags"):
                for tag in asset.contextual_tags.values():
                    category = tag.category.value
                    tags_by_category[category] = tags_by_category.get(category, 0) + 1
            
            # Count risk levels
            if hasattr(asset, "risk_assessment") and asset.risk_assessment:
                risk_level = asset.risk_assessment.risk_level.value
                risk_level_counts[risk_level] = risk_level_counts.get(risk_level, 0) + 1
        
        # Get most common tags
        most_common = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        most_common_tags = [{"tag": tag, "count": count} for tag, count in most_common]
        
        return TagStatsResponse(
            total_tags=len(tag_counts),
            tags_by_category=tags_by_category,
            most_common_tags=most_common_tags,
            assets_by_risk_level=risk_level_counts,
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/compliance/report")
async def get_compliance_report():
    """
    Get compliance report showing assets by risk level and requirements.
    """
    try:
        registry = get_registry()
        all_assets = registry.list_all()
        
        report = {
            "total_assets": len(all_assets),
            "by_risk_level": {
                "minimal": [],
                "limited": [],
                "high": [],
                "unacceptable": [],
            },
            "compliance_summary": {
                "compliant": 0,
                "requires_attention": 0,
                "non_compliant": 0,
            },
        }
        
        for asset in all_assets:
            asset_info = {
                "asset_id": asset.asset_id,
                "name": asset.name,
                "type": asset.asset_type.value,
                "tags": asset.tags,
            }
            
            if hasattr(asset, "risk_assessment") and asset.risk_assessment:
                risk_level = asset.risk_assessment.risk_level.value
                asset_info["requirements"] = asset.risk_assessment.requirements
                report["by_risk_level"][risk_level].append(asset_info)
                
                # Determine compliance status
                if not asset.risk_assessment.requirements:
                    report["compliance_summary"]["compliant"] += 1
                else:
                    report["compliance_summary"]["requires_attention"] += 1
            else:
                report["by_risk_level"]["minimal"].append(asset_info)
                report["compliance_summary"]["compliant"] += 1
        
        return report
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
