"""
Meta-Learning API Routes
Endpoints for agent learning, performance analytics, and optimization
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import timedelta

from backend.meta_learning import get_tracker, get_engine, MissionOutcome, OutcomeType
from backend.integrations.observability.prometheus_metrics import get_metrics

router = APIRouter(prefix="/api/v1/meta-learning", tags=["meta-learning"])

# Get instances
tracker = get_tracker()
engine = get_engine()
metrics = get_metrics()


@router.get("/performance/{agent_id}")
async def get_agent_performance(agent_id: str):
    """
    Get performance metrics for a specific agent

    Returns aggregated statistics including:
    - Success rate
    - Average cost and duration
    - Quality scores
    - Complexity breakdown
    - Recent trends
    """
    perf = tracker.get_agent_performance(agent_id)

    if not perf:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_id} not found or has no performance data",
        )

    return {
        "agent_id": perf.agent_id,
        "total_missions": perf.total_missions,
        "successful_missions": perf.successful_missions,
        "failed_missions": perf.failed_missions,
        "success_rate": round(perf.success_rate, 3),
        "total_cost": round(perf.total_cost, 2),
        "total_duration": round(perf.total_duration, 2),
        "avg_cost_per_mission": round(perf.avg_cost_per_mission, 2),
        "avg_duration_per_mission": round(perf.avg_duration_per_mission, 2),
        "average_quality": round(perf.average_quality, 3),
        "complexity_breakdown": perf.complexity_breakdown,
        "model_preferences": perf.model_preferences,
        "recent_trend": perf.recent_trend,
        "last_updated": perf.last_updated.isoformat(),
    }


@router.get("/performance")
async def get_all_agent_performance():
    """
    Get performance metrics for all agents

    Returns a dictionary of agent_id -> performance metrics
    """
    all_perf = tracker.get_all_agent_performance()

    return {
        "total_agents": len(all_perf),
        "agents": {
            agent_id: {
                "total_missions": perf.total_missions,
                "success_rate": round(perf.success_rate, 3),
                "avg_cost": round(perf.avg_cost_per_mission, 2),
                "trend": perf.recent_trend,
            }
            for agent_id, perf in all_perf.items()
        },
    }


@router.get("/leaderboard")
async def get_leaderboard(
    metric: str = Query("success_rate", description="Metric to rank by"),
    limit: int = Query(10, ge=1, le=100, description="Number of agents to return"),
):
    """
    Get top performing agents by a specific metric

    Available metrics:
    - success_rate: Percentage of successful missions
    - avg_cost_per_mission: Average cost efficiency
    - avg_duration_per_mission: Average speed
    - average_quality: Average output quality
    """
    valid_metrics = [
        "success_rate",
        "avg_cost_per_mission",
        "avg_duration_per_mission",
        "average_quality",
    ]

    if metric not in valid_metrics:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metric. Choose from: {', '.join(valid_metrics)}",
        )

    leaderboard = tracker.get_leaderboard(metric=metric, limit=limit)

    return {
        "metric": metric,
        "leaderboard": [
            {
                "rank": idx + 1,
                "agent_id": perf.agent_id,
                "value": round(getattr(perf, metric), 3),
                "total_missions": perf.total_missions,
                "success_rate": round(perf.success_rate, 3),
            }
            for idx, perf in enumerate(leaderboard)
        ],
    }


@router.get("/insights/{agent_id}")
async def get_learning_insights(agent_id: str):
    """
    Get actionable learning insights for an agent

    Provides:
    - Performance summary
    - Identified patterns
    - Recommendations for improvement
    - Best practices for this agent
    """
    insights = tracker.get_learning_insights(agent_id)
    return insights


@router.get("/analysis/{agent_id}")
async def analyze_agent(agent_id: str):
    """
    Comprehensive analysis of an agent's performance

    Includes:
    - Model performance analysis
    - Complexity analysis
    - Cost efficiency analysis
    - Quality analysis
    - Optimization recommendations
    """
    analysis = engine.analyze_agent(agent_id)
    return analysis


@router.get("/recommendations/{agent_id}")
async def get_recommendations(agent_id: str):
    """
    Get optimization recommendations for an agent

    Returns specific, actionable recommendations with:
    - Current vs recommended values
    - Expected improvement
    - Confidence level
    - Reasoning
    """
    recommendations = engine.get_recommendations(agent_id)

    return {
        "agent_id": agent_id,
        "recommendations": [
            {
                "category": rec.category,
                "current_value": rec.current_value,
                "recommended_value": rec.recommended_value,
                "expected_improvement": rec.expected_improvement,
                "confidence": round(rec.confidence, 2),
                "reasoning": rec.reasoning,
            }
            for rec in recommendations
        ],
    }


@router.post("/optimize/{agent_id}")
async def auto_optimize_agent(agent_id: str):
    """
    Automatically generate optimized configuration for an agent

    Analyzes performance data and creates an optimized configuration
    including:
    - Preferred model
    - Optimal complexity level
    - Cost limits
    - Quality thresholds
    """
    config = engine.auto_optimize(agent_id)

    return {
        "agent_id": config.agent_id,
        "configuration": {
            "preferred_model": config.preferred_model,
            "optimal_complexity": config.optimal_complexity,
            "max_cost_per_mission": (
                round(config.max_cost_per_mission, 2) if config.max_cost_per_mission else None
            ),
            "target_duration": (
                round(config.target_duration, 2) if config.target_duration else None
            ),
            "quality_threshold": round(config.quality_threshold, 3),
        },
        "last_optimized": (config.last_optimized.isoformat() if config.last_optimized else None),
    }


@router.get("/configuration/{agent_id}")
async def get_agent_configuration(agent_id: str):
    """
    Get the current optimized configuration for an agent

    Returns the configuration generated by auto-optimization
    """
    config = engine.get_configuration(agent_id)

    if not config:
        raise HTTPException(
            status_code=404,
            detail=f"No optimized configuration found for agent {agent_id}. Run /optimize/{agent_id} first.",  # noqa: E501
        )

    return {
        "agent_id": config.agent_id,
        "configuration": {
            "preferred_model": config.preferred_model,
            "optimal_complexity": config.optimal_complexity,
            "max_cost_per_mission": (
                round(config.max_cost_per_mission, 2) if config.max_cost_per_mission else None
            ),
            "target_duration": (
                round(config.target_duration, 2) if config.target_duration else None
            ),
            "quality_threshold": round(config.quality_threshold, 3),
        },
        "last_optimized": (config.last_optimized.isoformat() if config.last_optimized else None),
    }


@router.get("/complexity-insights")
async def get_complexity_insights():
    """
    Get insights about mission complexity across all agents

    Shows success rates, costs, and durations for each complexity level
    """
    insights = tracker.get_complexity_insights()
    return {"complexity_insights": insights}


@router.get("/system-insights")
async def get_system_insights():
    """
    Get system-wide insights across all agents

    Provides:
    - Overall statistics
    - Top performers
    - System-wide trends
    - Complexity analysis
    """
    insights = engine.get_system_insights()
    return insights


@router.get("/recent-outcomes")
async def get_recent_outcomes(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    limit: int = Query(50, ge=1, le=200, description="Number of outcomes to return"),
    hours: Optional[int] = Query(None, ge=1, le=720, description="Time window in hours"),
):
    """
    Get recent mission outcomes

    Useful for debugging and monitoring recent performance
    """
    time_window = timedelta(hours=hours) if hours else None
    outcomes = tracker.get_recent_outcomes(agent_id=agent_id, limit=limit, time_window=time_window)

    return {
        "count": len(outcomes),
        "outcomes": [
            {
                "mission_id": o.mission_id,
                "agent_id": o.agent_id,
                "timestamp": o.timestamp.isoformat(),
                "outcome": o.outcome.value,
                "duration_seconds": round(o.duration_seconds, 2),
                "cost": round(o.cost, 2),
                "complexity": o.complexity,
                "model_used": o.model_used,
                "quality_score": round(o.quality_score, 3),
                "error_message": o.error_message,
            }
            for o in outcomes
        ],
    }


@router.get("/stats")
async def get_meta_learning_stats():
    """
    Get overall meta-learning system statistics

    Quick overview of the learning system status
    """
    all_perf = tracker.get_all_agent_performance()

    total_missions = sum(p.total_missions for p in all_perf.values())
    total_successes = sum(p.successful_missions for p in all_perf.values())

    return {
        "total_agents_tracked": len(all_perf),
        "total_missions_recorded": total_missions,
        "overall_success_rate": (
            round(total_successes / total_missions, 3) if total_missions > 0 else 0
        ),
        "agents_with_data": len([p for p in all_perf.values() if p.total_missions > 0]),
        "agents_ready_for_optimization": len(
            [p for p in all_perf.values() if p.total_missions >= 10]
        ),
    }


@router.post("/record-outcome")
async def record_mission_outcome(outcome: dict):
    """
    Record a mission outcome for learning

    This endpoint is typically called by the mission executor
    after a mission completes.

    Expected payload:
    {
        "mission_id": "string",
        "agent_id": "string",
        "tenant_id": "string",
        "outcome": "success|failure|partial|error",
        "duration_seconds": float,
        "cost": float,
        "complexity": "simple|moderate|complex|swarm",
        "model_used": "string (optional)",
        "tokens_used": int (optional),
        "quality_score": float (optional),
        "error_message": "string (optional)"
    }
    """
    try:
        from datetime import datetime

        mission_outcome = MissionOutcome(
            mission_id=outcome["mission_id"],
            agent_id=outcome["agent_id"],
            tenant_id=outcome["tenant_id"],
            timestamp=datetime.utcnow(),
            outcome=OutcomeType(outcome["outcome"]),
            duration_seconds=outcome["duration_seconds"],
            cost=outcome["cost"],
            complexity=outcome["complexity"],
            model_used=outcome.get("model_used"),
            tokens_used=outcome.get("tokens_used", 0),
            quality_score=outcome.get("quality_score", 0.0),
            error_message=outcome.get("error_message"),
            metadata=outcome.get("metadata", {}),
        )

        tracker.record_outcome(mission_outcome)

        # Record in Prometheus metrics
        get_metrics().record_mission_complete(
            complexity=outcome["complexity"],
            status=outcome["outcome"],
            duration_seconds=outcome["duration_seconds"],
        )

        return {"status": "recorded", "mission_id": outcome["mission_id"]}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid outcome data: {str(e)}")


@router.delete("/clear-data")
async def clear_performance_data():
    """
    Clear all performance tracking data

    ⚠️ WARNING: This will delete all learning data!
    Use only for testing or reset purposes.
    """
    tracker.clear_data()
    return {"status": "cleared", "message": "All performance data has been cleared"}
