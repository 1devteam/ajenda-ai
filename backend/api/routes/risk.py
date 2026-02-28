"""
Risk Assessment API Routes for Omnipath V2.

This module provides REST API endpoints for:
1. Risk scoring and assessment
2. Approval workflow management
3. Impact assessment
4. Mitigation strategies

Author: Dev Team Lead
Date: 2026-02-26
Built with Pride for Obex Blackvault
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional

from ...agents.compliance.risk_scoring import (
    get_risk_scoring_engine,
    RiskTier,
)
from ...agents.compliance.approval_workflows import (
    get_approval_workflow,
)
from ...agents.compliance.impact_assessment import (
    get_impact_assessor,
)
from ...agents.compliance.regulatory_mapping import AuthorityLevel


router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


# ============================================================================
# Request/Response Models
# ============================================================================


class RiskScoreResponse(BaseModel):
    """Risk score response."""

    asset_id: str
    score: float
    tier: str
    breakdown: dict
    calculated_at: str
    expires_at: Optional[str]


class ApprovalRequestCreate(BaseModel):
    """Create approval request."""

    asset_id: str = Field(..., description="Asset identifier")
    operation: str = Field(..., description="Operation being performed")
    requester_id: str = Field(..., description="User requesting approval")
    justification: Optional[str] = Field(None, description="Justification for request")


class ApprovalRequestResponse(BaseModel):
    """Approval request response."""

    request_id: str
    asset_id: str
    operation: str
    requester_id: str
    risk_tier: str
    risk_score: float
    state: str
    created_at: str
    required_approver_level: int
    approver_id: Optional[str]
    approved_at: Optional[str]
    rejection_reason: Optional[str]
    escalation_reason: Optional[str]
    justification: Optional[str]
    notes: Optional[str]
    expires_at: Optional[str]


class ApprovalAction(BaseModel):
    """Approval action (approve/reject)."""

    approver_id: str = Field(..., description="User performing action")
    notes: Optional[str] = Field(None, description="Optional notes")
    reason: Optional[str] = Field(None, description="Reason (for rejection)")


class EscalationRequest(BaseModel):
    """Escalation request."""

    escalated_by: str = Field(..., description="User escalating")
    reason: str = Field(..., description="Escalation reason")


class ImpactScoreResponse(BaseModel):
    """Impact score response."""

    asset_id: str
    business_impact: float
    technical_impact: float
    compliance_impact: float
    overall_impact: float
    blast_radius: int
    affected_systems: List[str]
    assessed_at: str


class MitigationStrategyResponse(BaseModel):
    """Mitigation strategy response."""

    strategy_id: str
    name: str
    description: str
    risk_tier: str
    required: bool
    implementation_effort: str
    effectiveness: float
    cost_estimate: Optional[str]


# ============================================================================
# Risk Scoring Endpoints
# ============================================================================


@router.post("/assets/{asset_id}/calculate", response_model=RiskScoreResponse)
async def calculate_risk_score(asset_id: str):
    """
    Calculate risk score for an asset.

    This endpoint calculates a comprehensive risk score based on:
    - Inherent risk (EU AI Act level)
    - Data sensitivity (tags)
    - Operational context (production, user-facing, etc.)
    - Historical risk (past incidents)

    Returns:
        Risk score with breakdown by factor
    """
    try:
        engine = get_risk_scoring_engine()
        risk_score = engine.calculate_risk_score(asset_id)

        return RiskScoreResponse(
            asset_id=risk_score.asset_id,
            score=risk_score.score,
            tier=risk_score.tier.value,
            breakdown={k.value: v for k, v in risk_score.breakdown.items()},
            calculated_at=risk_score.calculated_at.isoformat(),
            expires_at=(risk_score.expires_at.isoformat() if risk_score.expires_at else None),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating risk score: {str(e)}")


@router.get("/assets/{asset_id}/score", response_model=RiskScoreResponse)
async def get_risk_score(asset_id: str):
    """
    Get current risk score for an asset (from cache if available).

    Returns cached score if available and not expired, otherwise calculates new score.

    Returns:
        Risk score with breakdown
    """
    try:
        engine = get_risk_scoring_engine()
        risk_score = engine.get_score(asset_id)

        if not risk_score:
            raise HTTPException(
                status_code=404, detail=f"Risk score not found for asset {asset_id}"
            )

        return RiskScoreResponse(
            asset_id=risk_score.asset_id,
            score=risk_score.score,
            tier=risk_score.tier.value,
            breakdown={k.value: v for k, v in risk_score.breakdown.items()},
            calculated_at=risk_score.calculated_at.isoformat(),
            expires_at=(risk_score.expires_at.isoformat() if risk_score.expires_at else None),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving risk score: {str(e)}")


@router.get("/assets/{asset_id}/breakdown", response_model=dict)
async def get_risk_breakdown(asset_id: str):
    """
    Get detailed risk breakdown by factor.

    Returns:
        Dictionary mapping risk factors to scores
    """
    try:
        engine = get_risk_scoring_engine()
        breakdown = engine.get_risk_breakdown(asset_id)

        return {k.value: v for k, v in breakdown.items()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting risk breakdown: {str(e)}")


@router.post("/recalculate-all", response_model=List[RiskScoreResponse])
async def recalculate_all_scores():
    """
    Recalculate risk scores for all assets.

    This is a maintenance endpoint for bulk recalculation.

    Returns:
        List of updated risk scores
    """
    try:
        engine = get_risk_scoring_engine()
        scores = engine.recalculate_all_scores()

        return [
            RiskScoreResponse(
                asset_id=score.asset_id,
                score=score.score,
                tier=score.tier.value,
                breakdown={k.value: v for k, v in score.breakdown.items()},
                calculated_at=score.calculated_at.isoformat(),
                expires_at=score.expires_at.isoformat() if score.expires_at else None,
            )
            for score in scores
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error recalculating scores: {str(e)}")


# ============================================================================
# Approval Workflow Endpoints
# ============================================================================


@router.post("/approvals", response_model=ApprovalRequestResponse)
async def create_approval_request(request: ApprovalRequestCreate):
    """
    Create an approval request for a high-risk operation.

    The system automatically determines the required approval level based on
    the asset's risk tier.

    Returns:
        Created approval request
    """
    try:
        workflow = get_approval_workflow()
        approval_request = workflow.create_approval_request(
            asset_id=request.asset_id,
            operation=request.operation,
            requester_id=request.requester_id,
            justification=request.justification,
        )

        return ApprovalRequestResponse(**approval_request.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating approval request: {str(e)}")


@router.get("/approvals/{request_id}", response_model=ApprovalRequestResponse)
async def get_approval_request(request_id: str):
    """
    Get approval request by ID.

    Returns:
        Approval request details
    """
    try:
        workflow = get_approval_workflow()
        request = workflow.get_request(request_id)

        if not request:
            raise HTTPException(status_code=404, detail=f"Approval request {request_id} not found")

        return ApprovalRequestResponse(**request.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving approval request: {str(e)}")


@router.get("/approvals", response_model=List[ApprovalRequestResponse])
async def get_pending_approvals(
    approver_level: Optional[int] = Query(None, description="Filter by authority level"),
):
    """
    Get pending approval requests.

    Optionally filter by approver authority level.

    Returns:
        List of pending approval requests
    """
    try:
        workflow = get_approval_workflow()

        authority = AuthorityLevel(approver_level) if approver_level is not None else None
        requests = workflow.get_pending_requests(approver_level=authority)

        return [ApprovalRequestResponse(**req.to_dict()) for req in requests]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving pending approvals: {str(e)}")


@router.post("/approvals/{request_id}/approve", response_model=ApprovalRequestResponse)
async def approve_request(request_id: str, action: ApprovalAction):
    """
    Approve an approval request.

    Returns:
        Updated approval request
    """
    try:
        workflow = get_approval_workflow()

        success = workflow.approve_request(
            request_id=request_id,
            approver_id=action.approver_id,
            notes=action.notes,
        )

        if not success:
            raise HTTPException(status_code=400, detail="Failed to approve request")

        request = workflow.get_request(request_id)
        return ApprovalRequestResponse(**request.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error approving request: {str(e)}")


@router.post("/approvals/{request_id}/reject", response_model=ApprovalRequestResponse)
async def reject_request(request_id: str, action: ApprovalAction):
    """
    Reject an approval request.

    Returns:
        Updated approval request
    """
    try:
        workflow = get_approval_workflow()

        if not action.reason:
            raise HTTPException(status_code=400, detail="Rejection reason is required")

        success = workflow.reject_request(
            request_id=request_id,
            approver_id=action.approver_id,
            reason=action.reason,
        )

        if not success:
            raise HTTPException(status_code=400, detail="Failed to reject request")

        request = workflow.get_request(request_id)
        return ApprovalRequestResponse(**request.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error rejecting request: {str(e)}")


@router.post("/approvals/{request_id}/escalate", response_model=ApprovalRequestResponse)
async def escalate_request(request_id: str, escalation: EscalationRequest):
    """
    Escalate an approval request to higher authority.

    Returns:
        Updated approval request
    """
    try:
        workflow = get_approval_workflow()

        success = workflow.escalate_request(
            request_id=request_id,
            escalated_by=escalation.escalated_by,
            reason=escalation.reason,
        )

        if not success:
            raise HTTPException(status_code=400, detail="Failed to escalate request")

        request = workflow.get_request(request_id)
        return ApprovalRequestResponse(**request.to_dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error escalating request: {str(e)}")


@router.get("/approvals/asset/{asset_id}/history", response_model=List[ApprovalRequestResponse])
async def get_approval_history(asset_id: str):
    """
    Get approval history for an asset.

    Returns:
        List of all approval requests for the asset
    """
    try:
        workflow = get_approval_workflow()
        requests = workflow.get_approval_history(asset_id)

        return [ApprovalRequestResponse(**req.to_dict()) for req in requests]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving approval history: {str(e)}")


@router.get("/approvals/check/{asset_id}", response_model=dict)
async def check_approval_required(
    asset_id: str, operation: str = Query(..., description="Operation")
):
    """
    Check if approval is required for an operation.

    Returns:
        Dictionary with required flag and risk tier
    """
    try:
        workflow = get_approval_workflow()
        required, tier = workflow.check_approval_required(asset_id, operation)

        return {
            "required": required,
            "risk_tier": tier.value if tier else None,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error checking approval requirement: {str(e)}"
        )


@router.post("/approvals/{request_id}/execute", response_model=ApprovalRequestResponse)
async def mark_executed(request_id: str):
    """
    Mark an approved request as executed.

    Returns:
        Updated approval request
    """
    try:
        workflow = get_approval_workflow()

        success = workflow.mark_executed(request_id)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to mark as executed")

        request = workflow.get_request(request_id)
        return ApprovalRequestResponse(**request.to_dict())
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error marking as executed: {str(e)}")


# ============================================================================
# Impact Assessment Endpoints
# ============================================================================


@router.post("/assets/{asset_id}/impact", response_model=ImpactScoreResponse)
async def assess_impact(asset_id: str):
    """
    Assess comprehensive impact for an asset.

    Evaluates three dimensions:
    - Business impact (revenue, customers, penalties, reputation)
    - Technical impact (dependencies, data volume, blast radius, RTO)
    - Compliance impact (requirements, audit trails, documentation)

    Returns:
        Impact score with breakdown
    """
    try:
        assessor = get_impact_assessor()
        impact = assessor.assess_impact(asset_id)

        return ImpactScoreResponse(
            asset_id=impact.asset_id,
            business_impact=impact.business_impact,
            technical_impact=impact.technical_impact,
            compliance_impact=impact.compliance_impact,
            overall_impact=impact.overall_impact,
            blast_radius=impact.blast_radius,
            affected_systems=impact.affected_systems,
            assessed_at=impact.assessed_at.isoformat(),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error assessing impact: {str(e)}")


@router.get("/assets/{asset_id}/blast-radius", response_model=dict)
async def get_blast_radius(asset_id: str):
    """
    Calculate blast radius for an asset.

    Returns:
        Dictionary with blast radius count
    """
    try:
        assessor = get_impact_assessor()
        blast_radius = assessor.calculate_blast_radius(asset_id)

        return {"asset_id": asset_id, "blast_radius": blast_radius}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error calculating blast radius: {str(e)}")


@router.get("/assets/{asset_id}/recovery-time", response_model=dict)
async def estimate_recovery_time(asset_id: str):
    """
    Estimate recovery time objective (RTO) for an asset.

    Returns:
        Dictionary with RTO in hours
    """
    try:
        assessor = get_impact_assessor()
        rto = assessor.estimate_recovery_time(asset_id)

        return {
            "asset_id": asset_id,
            "rto_hours": rto.total_seconds() / 3600,
            "rto_formatted": str(rto),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error estimating recovery time: {str(e)}")


@router.get(
    "/mitigation-strategies/{risk_tier}",
    response_model=List[MitigationStrategyResponse],
)
async def get_mitigation_strategies(risk_tier: str):
    """
    Get recommended mitigation strategies for a risk tier.

    Returns:
        List of mitigation strategies
    """
    try:
        # Validate risk tier
        tier = RiskTier(risk_tier)

        assessor = get_impact_assessor()
        strategies = assessor.get_mitigation_strategies(tier)

        return [
            MitigationStrategyResponse(
                strategy_id=s.strategy_id,
                name=s.name,
                description=s.description,
                risk_tier=s.risk_tier.value,
                required=s.required,
                implementation_effort=s.implementation_effort,
                effectiveness=s.effectiveness,
                cost_estimate=s.cost_estimate,
            )
            for s in strategies
        ]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid risk tier: {risk_tier}")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving mitigation strategies: {str(e)}"
        )


@router.get(
    "/mitigation-strategies/asset/{asset_id}",
    response_model=List[MitigationStrategyResponse],
)
async def get_asset_mitigation_strategies(asset_id: str):
    """
    Get recommended mitigation strategies for a specific asset.

    Returns:
        List of mitigation strategies based on asset's risk tier
    """
    try:
        # Get risk score
        engine = get_risk_scoring_engine()
        risk_score = engine.get_score(asset_id)

        if not risk_score:
            raise HTTPException(
                status_code=404, detail=f"Risk score not found for asset {asset_id}"
            )

        # Get mitigation strategies
        assessor = get_impact_assessor()
        strategies = assessor.get_mitigation_strategies(risk_score.tier)

        return [
            MitigationStrategyResponse(
                strategy_id=s.strategy_id,
                name=s.name,
                description=s.description,
                risk_tier=s.risk_tier.value,
                required=s.required,
                implementation_effort=s.implementation_effort,
                effectiveness=s.effectiveness,
                cost_estimate=s.cost_estimate,
            )
            for s in strategies
        ]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving mitigation strategies: {str(e)}"
        )
