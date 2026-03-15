"""
Revenue API Routes — Phase 5: The Revenue Agent
Handles leads, opportunities, proposals, deals, and revenue dashboard.

Built with Pride for Obex Blackvault
"""

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.routes.auth import get_current_user
from backend.database import get_db
from backend.database.models import Lead, Opportunity, Proposal, Deal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/revenue", tags=["revenue"])


# ============================================================================
# Lazy service getters
# ============================================================================


def _get_revenue_agent():
    try:
        from backend.main import get_revenue_agent

        return get_revenue_agent()
    except Exception:
        return None


def _get_event_store():
    try:
        from backend.main import get_event_store

        return get_event_store()
    except Exception:
        return None


# ============================================================================
# Request / Response Models
# ============================================================================


class LeadCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_linkedin: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    source: Optional[str] = Field(None, description="e.g. linkedin, reddit, manual")
    notes: Optional[str] = None
    research_data: Dict[str, Any] = Field(default_factory=dict)


class LeadUpdate(BaseModel):
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_linkedin: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    research_data: Optional[Dict[str, Any]] = None


class LeadResponse(BaseModel):
    id: str
    company_name: str
    contact_name: Optional[str]
    contact_email: Optional[str]
    contact_linkedin: Optional[str]
    industry: Optional[str]
    company_size: Optional[str]
    status: str
    source: Optional[str]
    qualification_score: Optional[float]
    qualification_notes: Optional[str]
    estimated_value: Optional[float]
    notes: Optional[str]
    tenant_id: str
    created_at: str
    updated_at: str


class QualifyLeadRequest(BaseModel):
    value_proposition: str = Field(
        ...,
        description="What Citadel offers — used to score fit",
    )
    ideal_customer_profile: str = Field(
        ...,
        description="ICP criteria for qualification scoring",
    )


class OpportunityResponse(BaseModel):
    id: str
    lead_id: str
    name: str
    status: str
    estimated_value: Optional[float]
    probability: Optional[float]
    contact_title: Optional[str]
    tenant_id: str
    created_at: str
    updated_at: str


class ProposalResponse(BaseModel):
    id: str
    opportunity_id: str
    title: str
    body: str
    status: str
    sent_to_email: Optional[str]
    sent_to_linkedin: Optional[str]
    tenant_id: str
    created_at: str
    updated_at: str


class DealResponse(BaseModel):
    id: str
    opportunity_id: str
    lead_id: str
    value: float
    currency: str
    payment_status: str
    closed_at: Optional[str]
    tenant_id: str
    created_at: str


class RunDealSagaRequest(BaseModel):
    lead_id: str
    agent_id: str
    value_proposition: str
    ideal_customer_profile: str
    send_outreach: bool = False


class RevenueDashboard(BaseModel):
    total_leads: int
    qualified_leads: int
    open_opportunities: int
    proposals_sent: int
    deals_closed: int
    total_revenue: float
    pipeline_value: float
    conversion_rate: float
    avg_deal_value: float
    top_industries: List[Dict[str, Any]]


# ============================================================================
# Helper
# ============================================================================


def _lead_to_response(lead: Lead) -> LeadResponse:
    return LeadResponse(
        id=lead.id,
        company_name=lead.company_name,
        contact_name=lead.contact_name,
        contact_email=lead.contact_email,
        contact_linkedin=lead.contact_linkedin,
        industry=lead.industry,
        company_size=lead.company_size,
        status=lead.status,
        source=lead.source,
        qualification_score=lead.qualification_score,
        qualification_notes=lead.qualification_notes,
        estimated_value=lead.estimated_value,
        notes=lead.notes,
        tenant_id=lead.tenant_id,
        created_at=lead.created_at.isoformat() if lead.created_at else "",
        updated_at=lead.updated_at.isoformat() if lead.updated_at else "",
    )


def _opp_to_response(opp: Opportunity) -> OpportunityResponse:
    return OpportunityResponse(
        id=opp.id,
        lead_id=opp.lead_id,
        name=opp.name,
        status=opp.status,
        estimated_value=opp.estimated_value,
        probability=opp.probability,
        contact_title=opp.contact_title,
        tenant_id=opp.tenant_id,
        created_at=opp.created_at.isoformat() if opp.created_at else "",
        updated_at=opp.updated_at.isoformat() if opp.updated_at else "",
    )


def _proposal_to_response(p: Proposal) -> ProposalResponse:
    return ProposalResponse(
        id=p.id,
        opportunity_id=p.opportunity_id,
        title=p.title,
        body=p.body,
        status=p.status,
        sent_to_email=p.sent_to_email,
        sent_to_linkedin=p.sent_to_linkedin,
        tenant_id=p.tenant_id,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
    )


def _deal_to_response(d: Deal) -> DealResponse:
    return DealResponse(
        id=d.id,
        opportunity_id=d.opportunity_id,
        lead_id=d.lead_id,
        value=d.value,
        currency=d.currency,
        payment_status=d.payment_status,
        closed_at=d.closed_at.isoformat() if d.closed_at else None,
        tenant_id=d.tenant_id,
        created_at=d.created_at.isoformat() if d.created_at else "",
    )


# ============================================================================
# Leads
# ============================================================================


@router.post("/leads", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Create a new lead."""
    tenant_id = current_user.get("tenant_id", "default")
    lead = Lead(
        id=f"lead_{uuid.uuid4().hex[:12]}",
        company_name=payload.company_name,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        contact_linkedin=payload.contact_linkedin,
        industry=payload.industry,
        company_size=payload.company_size,
        source=payload.source,
        notes=payload.notes,
        research_data=payload.research_data,
        tenant_id=tenant_id,
        status="new",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    logger.info(f"Lead created: {lead.id} ({lead.company_name})")
    return _lead_to_response(lead)


@router.get("/leads", response_model=List[LeadResponse])
async def list_leads(
    status_filter: Optional[str] = Query(None, alias="status"),
    industry: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[LeadResponse]:
    """List leads for the current tenant."""
    tenant_id = current_user.get("tenant_id", "default")
    q = db.query(Lead).filter(Lead.tenant_id == tenant_id)
    if status_filter:
        q = q.filter(Lead.status == status_filter)
    if industry:
        q = q.filter(Lead.industry == industry)
    leads = q.order_by(Lead.created_at.desc()).offset(offset).limit(limit).all()
    return [_lead_to_response(lead) for lead in leads]


@router.get("/leads/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Get a single lead by ID."""
    tenant_id = current_user.get("tenant_id", "default")
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.tenant_id == tenant_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _lead_to_response(lead)


@router.patch("/leads/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: str,
    payload: LeadUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """Update a lead."""
    tenant_id = current_user.get("tenant_id", "default")
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.tenant_id == tenant_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead, field, value)
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    return _lead_to_response(lead)


@router.delete("/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete a lead."""
    tenant_id = current_user.get("tenant_id", "default")
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.tenant_id == tenant_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    db.delete(lead)
    db.commit()


@router.post("/leads/{lead_id}/qualify", response_model=LeadResponse)
async def qualify_lead(
    lead_id: str,
    payload: QualifyLeadRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LeadResponse:
    """
    Run the RevenueAgent qualification workflow on a lead.
    Updates the lead's qualification_score, notes, and estimated_value.
    """
    tenant_id = current_user.get("tenant_id", "default")
    lead = db.query(Lead).filter(Lead.id == lead_id, Lead.tenant_id == tenant_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    revenue_agent = _get_revenue_agent()
    if not revenue_agent:
        raise HTTPException(
            status_code=503,
            detail="RevenueAgent not available",
        )

    try:
        from backend.orchestration.revenue_agent import LeadRecord

        lead_record = LeadRecord(
            id=lead.id,
            company_name=lead.company_name,
            tenant_id=lead.tenant_id,
            industry=lead.industry,
            company_size=lead.company_size,
            research_data=lead.research_data or {},
        )
        score, notes, contact_title, est_value, prob = await revenue_agent._qualify_lead(
            lead=lead_record,
            value_proposition=payload.value_proposition,
            ideal_customer_profile=payload.ideal_customer_profile,
        )
        lead.qualification_score = score
        lead.qualification_notes = notes
        lead.estimated_value = est_value
        lead.status = "qualified" if score >= 0.6 else "disqualified"
        lead.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(lead)
        return _lead_to_response(lead)
    except Exception as exc:
        logger.error(f"Lead qualification failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# Pipeline (Opportunities)
# ============================================================================


@router.get("/pipeline", response_model=List[OpportunityResponse])
async def get_pipeline(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[OpportunityResponse]:
    """Get all open opportunities (the sales pipeline)."""
    tenant_id = current_user.get("tenant_id", "default")
    q = db.query(Opportunity).filter(Opportunity.tenant_id == tenant_id)
    if status_filter:
        q = q.filter(Opportunity.status == status_filter)
    opps = q.order_by(Opportunity.created_at.desc()).offset(offset).limit(limit).all()
    return [_opp_to_response(o) for o in opps]


# ============================================================================
# Proposals
# ============================================================================


@router.get("/proposals", response_model=List[ProposalResponse])
async def list_proposals(
    opportunity_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[ProposalResponse]:
    """List proposals for the current tenant."""
    tenant_id = current_user.get("tenant_id", "default")
    q = db.query(Proposal).filter(Proposal.tenant_id == tenant_id)
    if opportunity_id:
        q = q.filter(Proposal.opportunity_id == opportunity_id)
    proposals = q.order_by(Proposal.created_at.desc()).limit(limit).all()
    return [_proposal_to_response(p) for p in proposals]


@router.get("/proposals/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProposalResponse:
    """Get a single proposal."""
    tenant_id = current_user.get("tenant_id", "default")
    proposal = (
        db.query(Proposal)
        .filter(Proposal.id == proposal_id, Proposal.tenant_id == tenant_id)
        .first()
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return _proposal_to_response(proposal)


# ============================================================================
# Deals
# ============================================================================


@router.get("/deals", response_model=List[DealResponse])
async def list_deals(
    payment_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[DealResponse]:
    """List closed deals for the current tenant."""
    tenant_id = current_user.get("tenant_id", "default")
    q = db.query(Deal).filter(Deal.tenant_id == tenant_id)
    if payment_status:
        q = q.filter(Deal.payment_status == payment_status)
    deals = q.order_by(Deal.created_at.desc()).limit(limit).all()
    return [_deal_to_response(d) for d in deals]


# ============================================================================
# Deal Closing Saga
# ============================================================================


@router.post("/run-deal-saga", status_code=status.HTTP_202_ACCEPTED)
async def run_deal_saga(
    payload: RunDealSagaRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Run the full DealClosingSaga for a lead.

    This dispatches the 7-step saga asynchronously:
    qualify → opportunity → proposal → outreach → response → close → revenue
    """
    tenant_id = current_user.get("tenant_id", "default")

    lead = db.query(Lead).filter(Lead.id == payload.lead_id, Lead.tenant_id == tenant_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    revenue_agent = _get_revenue_agent()
    event_store = _get_event_store()

    if not revenue_agent or not event_store:
        raise HTTPException(
            status_code=503,
            detail="RevenueAgent or EventStore not available",
        )

    try:
        from backend.core.saga.saga_orchestrator import DealClosingSaga, SagaOrchestrator

        orchestrator = SagaOrchestrator(event_store=event_store)
        saga = DealClosingSaga(
            orchestrator=orchestrator,
            revenue_agent=revenue_agent,
            event_store=event_store,
        )

        lead_data = {
            "company_name": lead.company_name,
            "industry": lead.industry,
            "company_size": lead.company_size,
            "research_data": lead.research_data or {},
            "contact_email": lead.contact_email,
            "contact_linkedin": lead.contact_linkedin,
        }

        result = await saga.execute(
            lead_id=lead.id,
            tenant_id=tenant_id,
            agent_id=payload.agent_id,
            value_proposition=payload.value_proposition,
            ideal_customer_profile=payload.ideal_customer_profile,
            lead_data=lead_data,
            send_outreach=payload.send_outreach,
        )

        # Persist deal to DB if saga succeeded
        if result.get("success") and result.get("deal_id"):
            deal = Deal(
                id=result["deal_id"],
                opportunity_id=result.get("opportunity_id", ""),
                lead_id=lead.id,
                value=result.get("revenue", 0.0),
                currency="USD",
                payment_status="pending",
                tenant_id=tenant_id,
                created_at=datetime.utcnow(),
            )
            db.add(deal)
            # Update lead status
            lead.status = "closed_won"
            lead.updated_at = datetime.utcnow()
            db.commit()

        return result

    except Exception as exc:
        logger.error(f"DealClosingSaga failed: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ============================================================================
# Revenue Dashboard
# ============================================================================


@router.get("/dashboard", response_model=RevenueDashboard)
async def get_revenue_dashboard(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RevenueDashboard:
    """
    Revenue dashboard — aggregated metrics for the current tenant.
    """
    tenant_id = current_user.get("tenant_id", "default")

    total_leads = db.query(Lead).filter(Lead.tenant_id == tenant_id).count()
    qualified_leads = (
        db.query(Lead).filter(Lead.tenant_id == tenant_id, Lead.status == "qualified").count()
    )
    open_opps = (
        db.query(Opportunity)
        .filter(
            Opportunity.tenant_id == tenant_id,
            Opportunity.status.in_(["open", "proposal_sent", "negotiating"]),
        )
        .count()
    )
    proposals_sent = (
        db.query(Proposal)
        .filter(
            Proposal.tenant_id == tenant_id,
            Proposal.status == "sent",
        )
        .count()
    )
    deals = db.query(Deal).filter(Deal.tenant_id == tenant_id).all()
    deals_closed = len(deals)
    total_revenue = sum(d.value for d in deals if d.payment_status == "paid")

    # Pipeline value = sum of estimated values of open opportunities
    open_opp_records = (
        db.query(Opportunity)
        .filter(
            Opportunity.tenant_id == tenant_id,
            Opportunity.status.in_(["open", "proposal_sent", "negotiating"]),
        )
        .all()
    )
    pipeline_value = sum(
        (o.estimated_value or 0.0) * (o.probability or 1.0) for o in open_opp_records
    )

    conversion_rate = deals_closed / total_leads if total_leads > 0 else 0.0
    avg_deal_value = total_revenue / deals_closed if deals_closed > 0 else 0.0

    # Top industries by lead count
    from sqlalchemy import func

    industry_counts = (
        db.query(Lead.industry, func.count(Lead.id).label("count"))
        .filter(Lead.tenant_id == tenant_id, Lead.industry.isnot(None))
        .group_by(Lead.industry)
        .order_by(func.count(Lead.id).desc())
        .limit(5)
        .all()
    )
    top_industries = [{"industry": row.industry, "count": row.count} for row in industry_counts]

    return RevenueDashboard(
        total_leads=total_leads,
        qualified_leads=qualified_leads,
        open_opportunities=open_opps,
        proposals_sent=proposals_sent,
        deals_closed=deals_closed,
        total_revenue=total_revenue,
        pipeline_value=pipeline_value,
        conversion_rate=round(conversion_rate, 4),
        avg_deal_value=round(avg_deal_value, 2),
        top_industries=top_industries,
    )
