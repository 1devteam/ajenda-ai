"""
Campaigns API Routes — Omnipath v2 Phase 3 (v6.2)

Provides endpoints for managing autonomous social media posting campaigns.
A campaign is a series of posts published by an agent on a target platform,
driven by the SocialMediaPostingSaga.

Endpoints:
    POST   /api/v1/campaigns           — Create and launch a campaign.
    GET    /api/v1/campaigns           — List campaigns for the current tenant.
    GET    /api/v1/campaigns/{id}      — Get campaign details and post history.
    POST   /api/v1/campaigns/{id}/run  — Trigger the next post in a campaign.

Built with Pride for Obex Blackvault
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.core.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateCampaignRequest(BaseModel):
    """Request body for creating a new campaign."""

    name: str = Field(..., min_length=1, max_length=200, description="Campaign name")
    platform: str = Field(
        ...,
        description="Target platform: twitter | reddit | linkedin",
        pattern="^(twitter|reddit|linkedin)$",
    )
    brief: str = Field(
        ...,
        min_length=10,
        max_length=2_000,
        description="Content brief for the LLM drafter",
    )
    agent_id: str = Field(..., description="Agent ID that will execute the campaign")
    total_posts: int = Field(
        default=1,
        ge=1,
        le=30,
        description="Total number of posts in the campaign",
    )
    post_interval_hours: float = Field(
        default=24.0,
        ge=0.1,
        le=168.0,
        description="Hours between posts (default 24h)",
    )
    auto_schedule: bool = Field(
        default=False,
        description="Automatically schedule subsequent posts",
    )


class CampaignResponse(BaseModel):
    """Campaign summary response."""

    id: str
    name: str
    platform: str
    brief: str
    agent_id: str
    tenant_id: str
    total_posts: int
    posts_published: int
    status: str
    created_at: str
    last_post_at: Optional[str] = None


class RunCampaignResponse(BaseModel):
    """Response from triggering a campaign post."""

    campaign_id: str
    post_index: int
    success: bool
    simulated: bool
    post_id: Optional[str] = None
    message: str


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------


def _get_current_user_id(request: Request) -> str:
    """Extract user_id from the JWT token stored on request.state."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return str(user.get("sub") or user.get("user_id") or user.get("id", ""))


def _get_tenant_id(request: Request) -> str:
    """Extract tenant_id from the JWT token stored on request.state."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return str(user.get("tenant_id", "default"))


def _get_saga_orchestrator(request: Request) -> Any:
    """Get the SagaOrchestrator from app.state."""
    orchestrator = getattr(request.app.state, "saga_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SagaOrchestrator not available",
        )
    return orchestrator


def _get_mission_executor(request: Request) -> Any:
    """Get the MissionExecutor from app.state."""
    executor = getattr(request.app.state, "mission_executor", None)
    if executor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MissionExecutor not available",
        )
    return executor


def _get_tool_bridge(request: Request) -> Any:
    """Get the MCPToolBridge from app.state."""
    from backend.integrations.mcp.tool_bridge import get_mcp_tool_bridge
    return get_mcp_tool_bridge()


def _get_event_store(request: Request) -> Any:
    """Get the EventStore from app.state."""
    event_store = getattr(request.app.state, "event_store", None)
    if event_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="EventStore not available",
        )
    return event_store


# ---------------------------------------------------------------------------
# In-memory campaign store (Redis-backed in production via EventStore replay)
# ---------------------------------------------------------------------------
# Campaigns are stored in the EventStore as events. This in-memory dict is a
# read model rebuilt from events at startup. For Phase 3, we use a simple
# dict; Phase 4 will add a proper CQRS read model.

_campaigns: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CreateCampaignRequest,
    request: Request,
    user_id: str = Depends(_get_current_user_id),
    tenant_id: str = Depends(_get_tenant_id),
) -> CampaignResponse:
    """
    Create a new social media posting campaign.

    The campaign is registered in the EventStore and the first post
    is queued for execution. Subsequent posts are scheduled automatically
    if ``auto_schedule`` is True.
    """
    campaign_id = f"campaign_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat()

    campaign = {
        "id": campaign_id,
        "name": body.name,
        "platform": body.platform,
        "brief": body.brief,
        "agent_id": body.agent_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "total_posts": body.total_posts,
        "posts_published": 0,
        "post_interval_hours": body.post_interval_hours,
        "auto_schedule": body.auto_schedule,
        "status": "active",
        "created_at": now,
        "last_post_at": None,
    }

    _campaigns[campaign_id] = campaign

    # Record campaign creation in EventStore
    event_store = _get_event_store(request)
    await event_store.append_event(
        aggregate_id=campaign_id,
        event_type="campaign.created",
        payload={
            "campaign_id": campaign_id,
            "name": body.name,
            "platform": body.platform,
            "agent_id": body.agent_id,
            "total_posts": body.total_posts,
        },
        tenant_id=tenant_id,
        user_id=user_id,
    )

    logger.info(f"Campaign created: {campaign_id} ({body.platform}, {body.total_posts} posts)")

    return CampaignResponse(**{k: v for k, v in campaign.items() if k in CampaignResponse.model_fields})


@router.get("", response_model=List[CampaignResponse])
async def list_campaigns(
    request: Request,
    tenant_id: str = Depends(_get_tenant_id),
) -> List[CampaignResponse]:
    """List all campaigns for the current tenant."""
    tenant_campaigns = [
        c for c in _campaigns.values()
        if c.get("tenant_id") == tenant_id
    ]
    return [
        CampaignResponse(**{k: v for k, v in c.items() if k in CampaignResponse.model_fields})
        for c in tenant_campaigns
    ]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    request: Request,
    tenant_id: str = Depends(_get_tenant_id),
) -> CampaignResponse:
    """Get campaign details by ID."""
    campaign = _campaigns.get(campaign_id)
    if not campaign or campaign.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign {campaign_id} not found",
        )
    return CampaignResponse(**{k: v for k, v in campaign.items() if k in CampaignResponse.model_fields})


@router.post("/{campaign_id}/run", response_model=RunCampaignResponse)
async def run_campaign_post(
    campaign_id: str,
    request: Request,
    user_id: str = Depends(_get_current_user_id),
    tenant_id: str = Depends(_get_tenant_id),
) -> RunCampaignResponse:
    """
    Trigger the next post in a campaign via the SocialMediaPostingSaga.

    This endpoint executes one post synchronously and returns the result.
    For scheduled campaigns, the SchedulerService calls this internally.
    """
    from backend.core.saga.saga_orchestrator import SocialMediaPostingSaga

    campaign = _campaigns.get(campaign_id)
    if not campaign or campaign.get("tenant_id") != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign {campaign_id} not found",
        )

    if campaign["posts_published"] >= campaign["total_posts"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Campaign {campaign_id} is already complete ({campaign['total_posts']} posts published)",
        )

    orchestrator = _get_saga_orchestrator(request)
    mission_executor = _get_mission_executor(request)
    tool_bridge = _get_tool_bridge(request)
    event_store = _get_event_store(request)

    post_index = campaign["posts_published"]

    saga = SocialMediaPostingSaga(
        orchestrator=orchestrator,
        mission_executor=mission_executor,
        tool_bridge=tool_bridge,
        event_store=event_store,
    )

    success = await saga.execute(
        campaign_id=campaign_id,
        agent_id=campaign["agent_id"],
        tenant_id=tenant_id,
        platform=campaign["platform"],
        brief=campaign["brief"],
        post_index=post_index,
        total_posts=campaign["total_posts"],
    )

    if success:
        campaign["posts_published"] += 1
        campaign["last_post_at"] = datetime.utcnow().isoformat()
        if campaign["posts_published"] >= campaign["total_posts"]:
            campaign["status"] = "completed"

    return RunCampaignResponse(
        campaign_id=campaign_id,
        post_index=post_index,
        success=success,
        simulated=True,  # Will be False when real platform credentials are configured
        message=(
            f"Post {post_index + 1}/{campaign['total_posts']} published successfully"
            if success
            else f"Post {post_index + 1}/{campaign['total_posts']} failed — saga compensated"
        ),
    )
