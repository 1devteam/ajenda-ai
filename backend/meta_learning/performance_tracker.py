"""
Performance Tracker - Meta-Learning System
Tracks agent and mission performance for learning and optimization
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class OutcomeType(Enum):
    """Mission outcome types"""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    ERROR = "error"


@dataclass
class MissionOutcome:
    """
    Record of a single mission execution outcome
    Used for learning and optimization
    """

    mission_id: str
    agent_id: str
    tenant_id: str
    timestamp: datetime
    outcome: OutcomeType
    duration_seconds: float
    cost: float
    complexity: str  # simple, moderate, complex, swarm
    model_used: Optional[str] = None
    tokens_used: int = 0
    error_message: Optional[str] = None
    quality_score: float = 0.0  # 0-1, based on output quality
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentPerformance:
    """
    Aggregated performance metrics for an agent
    """

    agent_id: str
    total_missions: int = 0
    successful_missions: int = 0
    failed_missions: int = 0
    total_cost: float = 0.0
    total_duration: float = 0.0
    average_quality: float = 0.0
    success_rate: float = 0.0
    avg_cost_per_mission: float = 0.0
    avg_duration_per_mission: float = 0.0
    complexity_breakdown: Dict[str, int] = field(default_factory=dict)
    model_preferences: Dict[str, int] = field(default_factory=dict)
    recent_trend: str = "stable"  # improving, declining, stable
    last_updated: datetime = field(default_factory=datetime.utcnow)


class PerformanceTracker:
    """
    Tracks and analyzes agent and mission performance

    Features:
    - Records mission outcomes
    - Calculates performance metrics
    - Identifies trends and patterns
    - Provides insights for optimization
    """

    def __init__(self):
        # In-memory storage (in production, use database)
        self._outcomes: List[MissionOutcome] = []
        self._agent_performance: Dict[str, AgentPerformance] = {}
        self._complexity_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "count": 0,
                "success_count": 0,
                "total_duration": 0.0,
                "total_cost": 0.0,
            }
        )
        logger.info("PerformanceTracker initialized")

    def record_outcome(self, outcome: MissionOutcome):
        """
        Record a mission outcome for learning

        Args:
            outcome: MissionOutcome with mission execution details
        """
        self._outcomes.append(outcome)
        self._update_agent_performance(outcome)
        self._update_complexity_stats(outcome)

        logger.debug(f"Recorded outcome for mission {outcome.mission_id}: {outcome.outcome.value}")

    def _update_agent_performance(self, outcome: MissionOutcome):
        """Update aggregated performance metrics for an agent"""
        agent_id = outcome.agent_id

        if agent_id not in self._agent_performance:
            self._agent_performance[agent_id] = AgentPerformance(agent_id=agent_id)

        perf = self._agent_performance[agent_id]
        perf.total_missions += 1
        perf.total_cost += outcome.cost
        perf.total_duration += outcome.duration_seconds

        if outcome.outcome == OutcomeType.SUCCESS:
            perf.successful_missions += 1
        elif outcome.outcome == OutcomeType.FAILURE:
            perf.failed_missions += 1

        # Update complexity breakdown
        perf.complexity_breakdown[outcome.complexity] = (
            perf.complexity_breakdown.get(outcome.complexity, 0) + 1
        )

        # Update model preferences
        if outcome.model_used:
            perf.model_preferences[outcome.model_used] = (
                perf.model_preferences.get(outcome.model_used, 0) + 1
            )

        # Recalculate averages
        perf.success_rate = perf.successful_missions / perf.total_missions
        perf.avg_cost_per_mission = perf.total_cost / perf.total_missions
        perf.avg_duration_per_mission = perf.total_duration / perf.total_missions

        # Calculate average quality
        agent_outcomes = [o for o in self._outcomes if o.agent_id == agent_id]
        if agent_outcomes:
            perf.average_quality = sum(o.quality_score for o in agent_outcomes) / len(
                agent_outcomes
            )

        # Determine trend (last 10 missions vs previous 10)
        perf.recent_trend = self._calculate_trend(agent_id)
        perf.last_updated = datetime.utcnow()

    def _update_complexity_stats(self, outcome: MissionOutcome):
        """Update statistics by complexity level"""
        stats = self._complexity_stats[outcome.complexity]
        stats["count"] += 1
        stats["total_duration"] += outcome.duration_seconds
        stats["total_cost"] += outcome.cost

        if outcome.outcome == OutcomeType.SUCCESS:
            stats["success_count"] += 1

    def _calculate_trend(self, agent_id: str) -> str:
        """
        Calculate performance trend for an agent
        Compares recent missions to previous missions
        """
        agent_outcomes = [o for o in self._outcomes if o.agent_id == agent_id]

        if len(agent_outcomes) < 20:
            return "stable"  # Not enough data

        # Split into recent and previous
        recent = agent_outcomes[-10:]
        previous = agent_outcomes[-20:-10]

        recent_success_rate = sum(1 for o in recent if o.outcome == OutcomeType.SUCCESS) / len(
            recent
        )
        previous_success_rate = sum(1 for o in previous if o.outcome == OutcomeType.SUCCESS) / len(
            previous
        )

        diff = recent_success_rate - previous_success_rate

        if diff > 0.1:
            return "improving"
        elif diff < -0.1:
            return "declining"
        else:
            return "stable"

    def get_agent_performance(self, agent_id: str) -> Optional[AgentPerformance]:
        """
        Get performance metrics for a specific agent

        Args:
            agent_id: Agent identifier

        Returns:
            AgentPerformance object or None if agent not found
        """
        return self._agent_performance.get(agent_id)

    def get_all_agent_performance(self) -> Dict[str, AgentPerformance]:
        """Get performance metrics for all agents"""
        return self._agent_performance.copy()

    def get_leaderboard(
        self, metric: str = "success_rate", limit: int = 10
    ) -> List[AgentPerformance]:
        """
        Get top performing agents by a specific metric

        Args:
            metric: Metric to sort by (success_rate, avg_cost_per_mission, etc.)
            limit: Number of agents to return

        Returns:
            List of AgentPerformance objects sorted by metric
        """
        agents = list(self._agent_performance.values())

        # Sort by metric (higher is better for success_rate, lower for cost/duration)
        if metric in ["avg_cost_per_mission", "avg_duration_per_mission"]:
            agents.sort(key=lambda a: getattr(a, metric))
        else:
            agents.sort(key=lambda a: getattr(a, metric), reverse=True)

        return agents[:limit]

    def get_complexity_insights(self) -> Dict[str, Dict[str, Any]]:
        """
        Get insights about mission complexity

        Returns:
            Dictionary with stats for each complexity level
        """
        insights = {}

        for complexity, stats in self._complexity_stats.items():
            if stats["count"] > 0:
                insights[complexity] = {
                    "total_missions": stats["count"],
                    "success_rate": stats["success_count"] / stats["count"],
                    "avg_duration": stats["total_duration"] / stats["count"],
                    "avg_cost": stats["total_cost"] / stats["count"],
                }

        return insights

    def get_recent_outcomes(
        self,
        agent_id: Optional[str] = None,
        limit: int = 50,
        time_window: Optional[timedelta] = None,
    ) -> List[MissionOutcome]:
        """
        Get recent mission outcomes

        Args:
            agent_id: Filter by agent (optional)
            limit: Maximum number of outcomes to return
            time_window: Only return outcomes within this time window (optional)

        Returns:
            List of MissionOutcome objects
        """
        outcomes = self._outcomes

        # Filter by agent
        if agent_id:
            outcomes = [o for o in outcomes if o.agent_id == agent_id]

        # Filter by time window
        if time_window:
            cutoff = datetime.utcnow() - time_window
            outcomes = [o for o in outcomes if o.timestamp >= cutoff]

        # Sort by timestamp (most recent first) and limit
        outcomes.sort(key=lambda o: o.timestamp, reverse=True)
        return outcomes[:limit]

    def get_learning_insights(self, agent_id: str) -> Dict[str, Any]:
        """
        Get actionable learning insights for an agent

        Args:
            agent_id: Agent identifier

        Returns:
            Dictionary with insights and recommendations
        """
        perf = self.get_agent_performance(agent_id)

        if not perf:
            return {"error": "Agent not found"}

        agent_outcomes = [o for o in self._outcomes if o.agent_id == agent_id]

        if len(agent_outcomes) < 5:
            return {
                "message": "Not enough data for insights (minimum 5 missions required)",
                "missions_completed": len(agent_outcomes),
            }

        # Analyze patterns
        insights = {
            "overall_performance": {
                "success_rate": perf.success_rate,
                "total_missions": perf.total_missions,
                "trend": perf.recent_trend,
            },
            "cost_efficiency": {
                "avg_cost": perf.avg_cost_per_mission,
                "total_spent": perf.total_cost,
            },
            "speed": {
                "avg_duration": perf.avg_duration_per_mission,
                "total_time": perf.total_duration,
            },
            "quality": {"avg_score": perf.average_quality},
            "recommendations": [],
        }

        # Generate recommendations
        if perf.success_rate < 0.7:
            insights["recommendations"].append(
                {
                    "type": "success_rate",
                    "message": "Success rate is below 70%. Consider adjusting mission complexity or agent configuration.",  # noqa: E501
                    "priority": "high",
                }
            )

        if perf.avg_cost_per_mission > 5.0:
            insights["recommendations"].append(
                {
                    "type": "cost",
                    "message": "Average cost per mission is high. Consider using more efficient models.",  # noqa: E501
                    "priority": "medium",
                }
            )

        if perf.recent_trend == "declining":
            insights["recommendations"].append(
                {
                    "type": "trend",
                    "message": "Performance is declining. Review recent failures and adjust strategy.",  # noqa: E501
                    "priority": "high",
                }
            )

        # Best complexity level for this agent
        if perf.complexity_breakdown:
            best_complexity = max(perf.complexity_breakdown.items(), key=lambda x: x[1])
            insights["best_complexity"] = best_complexity[0]

        # Most used model
        if perf.model_preferences:
            most_used_model = max(perf.model_preferences.items(), key=lambda x: x[1])
            insights["preferred_model"] = most_used_model[0]

        return insights

    def clear_data(self):
        """Clear all tracked data (for testing/reset)"""
        self._outcomes.clear()
        self._agent_performance.clear()
        self._complexity_stats.clear()
        logger.info("Performance data cleared")


# Global tracker instance
_tracker: Optional[PerformanceTracker] = None


def get_tracker() -> PerformanceTracker:
    """Get the global performance tracker instance"""
    global _tracker
    if _tracker is None:
        _tracker = PerformanceTracker()
    return _tracker
