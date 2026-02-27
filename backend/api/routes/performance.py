"""
Agent Performance & Self-Improvement API Routes
Monitor agent learning and optimization

Built with Pride for Obex Blackvault
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from backend.middleware.auth.auth_middleware import get_current_user
from backend.database.session import get_db
from backend.database.models import Agent, Mission
from backend.models.domain.user import User

router = APIRouter(prefix="/api/v1/performance", tags=["performance"])


# ============================================================================
# Response Models
# ============================================================================

class AgentPerformanceMetrics(BaseModel):
    """Performance metrics for an agent"""
    agent_id: str
    agent_type: str
    total_missions: int
    successful_missions: int
    failed_missions: int
    success_rate: float
    average_duration_seconds: float
    average_cost: float
    total_improvements: int
    last_improvement_date: Optional[datetime] = None
    current_strategy_version: int


class ImprovementEvent(BaseModel):
    """Self-improvement event record"""
    improvement_id: str
    agent_id: str
    timestamp: datetime
    trigger_reason: str
    old_strategy: str
    new_strategy: str
    performance_before: Dict[str, float]
    performance_after: Optional[Dict[str, float]] = None
    improvement_type: str  # "prompt_optimization", "model_switch", "parameter_tuning"


class PerformanceTrend(BaseModel):
    """Performance trend over time"""
    agent_id: str
    date: datetime
    success_rate: float
    average_cost: float
    average_duration: float
    missions_count: int


# ============================================================================
# Helpers
# ============================================================================

def _build_performance_metrics(agent: Agent, db: Session) -> AgentPerformanceMetrics:
    """
    Compute performance metrics for a single agent from the missions table.

    Args:
        agent: SQLAlchemy Agent instance.
        db:    Database session.

    Returns:
        Populated :class:`AgentPerformanceMetrics`.
    """
    # Aggregate from missions table for accuracy (agent columns may be stale)
    agg = (
        db.query(
            func.count(Mission.id).label("total"),
            func.sum(
                func.cast(Mission.status == "COMPLETED", int)
            ).label("successful"),
            func.sum(
                func.cast(Mission.status == "FAILED", int)
            ).label("failed"),
            func.avg(Mission.execution_time).label("avg_duration"),
            func.avg(Mission.cost).label("avg_cost"),
        )
        .filter(Mission.agent_id == agent.id)
        .one()
    )

    total = agg.total or 0
    successful = int(agg.successful or 0)
    failed = int(agg.failed or 0)
    avg_duration = float(agg.avg_duration or 0.0)
    avg_cost = float(agg.avg_cost or 0.0)
    success_rate = (successful / total) if total > 0 else 0.0

    return AgentPerformanceMetrics(
        agent_id=agent.id,
        agent_type=agent.type,
        total_missions=total,
        successful_missions=successful,
        failed_missions=failed,
        success_rate=round(success_rate, 4),
        average_duration_seconds=round(avg_duration, 2),
        average_cost=round(avg_cost, 4),
        # Improvement tracking is stored in agent.config; default to 0 if absent
        total_improvements=int(
            agent.config.get("total_improvements", 0)
            if isinstance(agent.config, dict)
            else 0
        ),
        last_improvement_date=(
            datetime.fromisoformat(agent.config["last_improvement_date"])
            if isinstance(agent.config, dict)
            and agent.config.get("last_improvement_date")
            else None
        ),
        current_strategy_version=int(
            agent.config.get("strategy_version", 1)
            if isinstance(agent.config, dict)
            else 1
        ),
    )


# ============================================================================
# Endpoints
# ============================================================================

@router.get("/agents", response_model=List[AgentPerformanceMetrics])
async def get_all_agent_performance(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get performance metrics for all agents in the tenant.

    Returns success rates, costs, and self-improvement activity computed
    directly from the missions table.
    """
    agents: List[Agent] = (
        db.query(Agent)
        .filter(Agent.tenant_id == current_user.tenant_id)
        .all()
    )

    return [_build_performance_metrics(agent, db) for agent in agents]


@router.get("/agents/{agent_id}", response_model=AgentPerformanceMetrics)
async def get_agent_performance(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get performance metrics for a specific agent.

    Raises 404 if the agent does not exist or belongs to a different tenant.
    """
    agent: Optional[Agent] = (
        db.query(Agent)
        .filter(
            Agent.id == agent_id,
            Agent.tenant_id == current_user.tenant_id,
        )
        .first()
    )

    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found",
        )

    return _build_performance_metrics(agent, db)


@router.get("/improvements", response_model=List[ImprovementEvent])
async def get_improvement_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    agent_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get self-improvement event history.

    Improvement events are stored in ``agent.config["improvements"]``.
    Returns an empty list if no improvements have been recorded.
    """
    query = db.query(Agent).filter(Agent.tenant_id == current_user.tenant_id)
    if agent_id:
        query = query.filter(Agent.id == agent_id)

    agents: List[Agent] = query.all()

    events: List[ImprovementEvent] = []
    for agent in agents:
        improvements = (
            agent.config.get("improvements", [])
            if isinstance(agent.config, dict)
            else []
        )
        for imp in improvements:
            try:
                events.append(
                    ImprovementEvent(
                        improvement_id=imp.get("id", ""),
                        agent_id=agent.id,
                        timestamp=datetime.fromisoformat(imp["timestamp"]),
                        trigger_reason=imp.get("trigger_reason", ""),
                        old_strategy=imp.get("old_strategy", ""),
                        new_strategy=imp.get("new_strategy", ""),
                        performance_before=imp.get("performance_before", {}),
                        performance_after=imp.get("performance_after"),
                        improvement_type=imp.get("improvement_type", "unknown"),
                    )
                )
            except (KeyError, ValueError):
                continue

    # Sort by timestamp descending, then paginate
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events[offset : offset + limit]


@router.get("/trends/{agent_id}", response_model=List[PerformanceTrend])
async def get_performance_trends(
    agent_id: str,
    days: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get performance trends over time for an agent.

    Aggregates mission data by calendar day over the requested window and
    returns one data point per day that had at least one mission.

    Raises 404 if the agent does not exist or belongs to a different tenant.
    """
    # Verify agent ownership
    agent: Optional[Agent] = (
        db.query(Agent)
        .filter(
            Agent.id == agent_id,
            Agent.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found",
        )

    since = datetime.utcnow() - timedelta(days=days)

    missions: List[Mission] = (
        db.query(Mission)
        .filter(
            Mission.agent_id == agent_id,
            Mission.created_at >= since,
        )
        .order_by(Mission.created_at)
        .all()
    )

    # Group by date
    daily: Dict[datetime, List[Mission]] = {}
    for m in missions:
        day = m.created_at.replace(hour=0, minute=0, second=0, microsecond=0)
        daily.setdefault(day, []).append(m)

    trends: List[PerformanceTrend] = []
    for day, day_missions in sorted(daily.items()):
        total = len(day_missions)
        successful = sum(1 for m in day_missions if m.status == "COMPLETED")
        costs = [m.cost for m in day_missions if m.cost is not None]
        durations = [m.execution_time for m in day_missions if m.execution_time is not None]

        trends.append(
            PerformanceTrend(
                agent_id=agent_id,
                date=day,
                success_rate=round(successful / total, 4) if total > 0 else 0.0,
                average_cost=round(sum(costs) / len(costs), 4) if costs else 0.0,
                average_duration=round(sum(durations) / len(durations), 2) if durations else 0.0,
                missions_count=total,
            )
        )

    return trends


@router.post("/trigger-improvement/{agent_id}")
async def trigger_manual_improvement(
    agent_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Manually trigger self-improvement analysis for an agent.

    Normally happens automatically every 10 missions.  This endpoint queues
    an immediate analysis regardless of the mission count threshold.
    """
    agent: Optional[Agent] = (
        db.query(Agent)
        .filter(
            Agent.id == agent_id,
            Agent.tenant_id == current_user.tenant_id,
        )
        .first()
    )
    if agent is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent_id}' not found",
        )

    # Record the manual trigger in agent config for audit trail
    if not isinstance(agent.config, dict):
        agent.config = {}
    agent.config["manual_improvement_requested_at"] = datetime.utcnow().isoformat()
    db.commit()

    return {
        "message": f"Improvement analysis triggered for agent {agent_id}",
        "status": "queued",
        "agent_id": agent_id,
        "queued_at": datetime.utcnow().isoformat(),
    }
