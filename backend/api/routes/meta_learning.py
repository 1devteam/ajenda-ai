"""
Meta-Learning API Routes
Endpoints for agent learning, adaptation, and performance insights
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import timedelta

from backend.meta_learning.performance_tracker import (
    get_tracker, 
    MissionOutcome
)
from backend.meta_learning.adaptive_engine import get_engine

router = APIRouter(prefix="/api/v1/meta-learning", tags=["meta-learning"])


@router.get("/performance/{agent_id}")
async def get_agent_performance(
    agent_id: str,
    days: Optional[int] = Query(None, description="Time window in days")
):
    """
    Get performance metrics for an agent
    
    Shows how well the agent is doing - like a report card
    """
    tracker = get_tracker()
    
    time_window = timedelta(days=days) if days else None
    performance = tracker.get_agent_performance(agent_id, time_window)
    
    if performance['total_missions'] == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No performance data found for agent {agent_id}"
        )
    
    return performance


@router.get("/leaderboard")
async def get_leaderboard(
    top_n: int = Query(10, description="Number of top agents to return"),
    metric: str = Query("success_rate", description="Metric to rank by")
):
    """
    Get the top performing agents
    
    Like a high score board - who's the best?
    """
    tracker = get_tracker()
    
    valid_metrics = ['success_rate', 'avg_quality', 'total_missions', 'avg_cost']
    if metric not in valid_metrics:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metric. Must be one of: {valid_metrics}"
        )
    
    leaderboard = tracker.get_best_performing_agents(top_n, metric)
    
    return {
        'metric': metric,
        'top_agents': leaderboard
    }


@router.get("/insights/{agent_id}")
async def get_learning_insights(agent_id: str):
    """
    Get actionable insights for improving agent performance
    
    Like getting feedback from a teacher - what can you improve?
    """
    tracker = get_tracker()
    insights = tracker.get_learning_insights(agent_id)
    
    return insights


@router.get("/comparison/{agent_id}")
async def compare_configurations(agent_id: str):
    """
    Compare different configuration settings for an agent
    
    Shows which settings work best - like A/B testing results
    """
    tracker = get_tracker()
    comparison = tracker.compare_configurations(agent_id)
    
    return comparison


@router.get("/optimal-config/{agent_id}")
async def get_optimal_config(
    agent_id: str,
    mission_type: Optional[str] = None
):
    """
    Get the optimal configuration for an agent based on learning
    
    Tells you the best settings to use based on past performance
    """
    engine = get_engine()
    
    if not engine.should_adapt(agent_id):
        return {
            'status': 'insufficient_data',
            'message': 'Not enough missions yet - need at least 10',
            'config': engine.default_config
        }
    
    config = engine.get_optimal_config(agent_id, mission_type)
    
    return {
        'status': 'optimized',
        'agent_id': agent_id,
        'config': config,
        'message': 'Configuration optimized based on historical performance'
    }


@router.post("/auto-tune/{agent_id}")
async def auto_tune_agent(
    agent_id: str,
    aggressive: bool = Query(False, description="Use aggressive tuning")
):
    """
    Automatically tune agent configuration
    
    Like hitting the "optimize" button - let the system figure out best settings
    """
    engine = get_engine()
    
    config, explanation = engine.auto_tune(agent_id, aggressive)
    
    return {
        'agent_id': agent_id,
        'new_config': config,
        'explanation': explanation,
        'aggressive_mode': aggressive
    }


@router.get("/improvement/{agent_id}")
async def calculate_improvement(
    agent_id: str,
    window_days: int = Query(7, description="Days to look back")
):
    """
    Calculate how much an agent has improved over time
    
    Shows if the agent is getting better or worse
    """
    engine = get_engine()
    improvement = engine.calculate_improvement(agent_id, window_days)
    
    return improvement


@router.get("/experiment/{agent_id}")
async def suggest_experiment(agent_id: str):
    """
    Suggest a configuration experiment to try
    
    Like a scientist suggesting: "Let's try this and see what happens"
    """
    engine = get_engine()
    experiment = engine.suggest_experiment(agent_id)
    
    if not experiment:
        return {
            'status': 'no_experiment',
            'message': 'Not enough data to suggest experiments yet'
        }
    
    return {
        'status': 'experiment_suggested',
        'agent_id': agent_id,
        'experiment': experiment
    }


@router.get("/stats")
async def get_meta_learning_stats():
    """
    Get overall meta-learning system statistics
    
    High-level view of how the learning system is doing
    """
    tracker = get_tracker()
    
    total_outcomes = len(tracker.outcomes)
    total_agents = len(tracker.agent_stats)
    
    if total_outcomes == 0:
        return {
            'total_outcomes': 0,
            'total_agents': 0,
            'message': 'No learning data yet'
        }
    
    # Calculate overall success rate
    successful = sum(1 for o in tracker.outcomes if o.status == 'completed')
    overall_success_rate = successful / total_outcomes if total_outcomes > 0 else 0
    
    # Find agents that have adapted
    adapted_agents = sum(1 for agent_id in tracker.agent_stats.keys()
                        if tracker.agent_stats[agent_id]['total_missions'] >= 10)
    
    return {
        'total_outcomes': total_outcomes,
        'total_agents': total_agents,
        'adapted_agents': adapted_agents,
        'overall_success_rate': round(overall_success_rate, 3),
        'total_missions': total_outcomes,
        'learning_active': adapted_agents > 0
    }
