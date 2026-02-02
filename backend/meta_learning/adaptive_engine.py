"""
Adaptive Learning Engine - Meta-Learning System
Learns from performance data and optimizes agent configurations
"""
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from backend.meta_learning.performance_tracker import (
    PerformanceTracker,
    get_tracker,
    OutcomeType
)

logger = logging.getLogger(__name__)


@dataclass
class OptimizationRecommendation:
    """
    A recommendation for optimizing agent performance
    """
    agent_id: str
    category: str  # model, complexity, cost, speed
    current_value: Any
    recommended_value: Any
    expected_improvement: str
    confidence: float  # 0-1
    reasoning: str


@dataclass
class AgentConfiguration:
    """
    Optimized configuration for an agent
    """
    agent_id: str
    preferred_model: Optional[str] = None
    optimal_complexity: Optional[str] = None
    max_cost_per_mission: Optional[float] = None
    target_duration: Optional[float] = None
    quality_threshold: float = 0.7
    last_optimized: datetime = None


class AdaptiveLearningEngine:
    """
    Learns from agent performance and provides optimization recommendations
    
    Features:
    - Analyzes performance patterns
    - Identifies optimal configurations
    - Provides actionable recommendations
    - Auto-tunes agent settings (optional)
    """
    
    def __init__(self, tracker: Optional[PerformanceTracker] = None):
        self.tracker = tracker or get_tracker()
        self._configurations: Dict[str, AgentConfiguration] = {}
        logger.info("AdaptiveLearningEngine initialized")
    
    def analyze_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Comprehensive analysis of an agent's performance
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Dictionary with analysis results and recommendations
        """
        perf = self.tracker.get_agent_performance(agent_id)
        
        if not perf:
            return {"error": f"Agent {agent_id} not found"}
        
        if perf.total_missions < 10:
            return {
                "error": "Insufficient data for analysis",
                "message": "Agent needs at least 10 completed missions for meaningful analysis",
                "current_missions": perf.total_missions
            }
        
        # Gather all analysis components
        analysis = {
            "agent_id": agent_id,
            "timestamp": datetime.utcnow().isoformat(),
            "performance_summary": self._summarize_performance(perf),
            "model_analysis": self._analyze_model_performance(agent_id),
            "complexity_analysis": self._analyze_complexity_performance(agent_id),
            "cost_analysis": self._analyze_cost_efficiency(agent_id),
            "quality_analysis": self._analyze_quality(agent_id),
            "recommendations": self.get_recommendations(agent_id)
        }
        
        return analysis
    
    def _summarize_performance(self, perf) -> Dict[str, Any]:
        """Create a summary of overall performance"""
        return {
            "total_missions": perf.total_missions,
            "success_rate": round(perf.success_rate, 3),
            "avg_cost": round(perf.avg_cost_per_mission, 2),
            "avg_duration": round(perf.avg_duration_per_mission, 2),
            "avg_quality": round(perf.average_quality, 3),
            "trend": perf.recent_trend,
            "grade": self._calculate_grade(perf)
        }
    
    def _calculate_grade(self, perf) -> str:
        """Calculate an overall performance grade (A-F)"""
        score = 0
        
        # Success rate (40%)
        score += perf.success_rate * 40
        
        # Quality (30%)
        score += perf.average_quality * 30
        
        # Cost efficiency (15%) - inverse, lower is better
        cost_score = max(0, (10 - perf.avg_cost_per_mission) / 10) * 15
        score += cost_score
        
        # Speed (15%) - inverse, faster is better
        speed_score = max(0, (60 - perf.avg_duration_per_mission) / 60) * 15
        score += speed_score
        
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"
    
    def _analyze_model_performance(self, agent_id: str) -> Dict[str, Any]:
        """Analyze which models perform best for this agent"""
        outcomes = self.tracker.get_recent_outcomes(agent_id=agent_id, limit=100)
        
        if not outcomes:
            return {}
        
        model_stats = {}
        for outcome in outcomes:
            if not outcome.model_used:
                continue
            
            if outcome.model_used not in model_stats:
                model_stats[outcome.model_used] = {
                    "count": 0,
                    "successes": 0,
                    "total_cost": 0.0,
                    "total_duration": 0.0,
                    "total_quality": 0.0
                }
            
            stats = model_stats[outcome.model_used]
            stats["count"] += 1
            stats["total_cost"] += outcome.cost
            stats["total_duration"] += outcome.duration_seconds
            stats["total_quality"] += outcome.quality_score
            
            if outcome.outcome == OutcomeType.SUCCESS:
                stats["successes"] += 1
        
        # Calculate averages and find best model
        best_model = None
        best_score = 0
        
        for model, stats in model_stats.items():
            stats["success_rate"] = stats["successes"] / stats["count"]
            stats["avg_cost"] = stats["total_cost"] / stats["count"]
            stats["avg_duration"] = stats["total_duration"] / stats["count"]
            stats["avg_quality"] = stats["total_quality"] / stats["count"]
            
            # Calculate composite score (success_rate * quality / cost)
            score = (stats["success_rate"] * stats["avg_quality"]) / max(stats["avg_cost"], 0.1)
            stats["composite_score"] = round(score, 3)
            
            if score > best_score:
                best_score = score
                best_model = model
        
        return {
            "models": model_stats,
            "recommended_model": best_model
        }
    
    def _analyze_complexity_performance(self, agent_id: str) -> Dict[str, Any]:
        """Analyze which complexity levels work best for this agent"""
        outcomes = self.tracker.get_recent_outcomes(agent_id=agent_id, limit=100)
        
        if not outcomes:
            return {}
        
        complexity_stats = {}
        for outcome in outcomes:
            if outcome.complexity not in complexity_stats:
                complexity_stats[outcome.complexity] = {
                    "count": 0,
                    "successes": 0,
                    "total_cost": 0.0,
                    "total_duration": 0.0
                }
            
            stats = complexity_stats[outcome.complexity]
            stats["count"] += 1
            stats["total_cost"] += outcome.cost
            stats["total_duration"] += outcome.duration_seconds
            
            if outcome.outcome == OutcomeType.SUCCESS:
                stats["successes"] += 1
        
        # Calculate success rates and find optimal complexity
        best_complexity = None
        best_success_rate = 0
        
        for complexity, stats in complexity_stats.items():
            stats["success_rate"] = stats["successes"] / stats["count"]
            stats["avg_cost"] = stats["total_cost"] / stats["count"]
            stats["avg_duration"] = stats["total_duration"] / stats["count"]
            
            if stats["success_rate"] > best_success_rate:
                best_success_rate = stats["success_rate"]
                best_complexity = complexity
        
        return {
            "complexity_levels": complexity_stats,
            "recommended_complexity": best_complexity
        }
    
    def _analyze_cost_efficiency(self, agent_id: str) -> Dict[str, Any]:
        """Analyze cost efficiency and identify savings opportunities"""
        outcomes = self.tracker.get_recent_outcomes(agent_id=agent_id, limit=100)
        
        if not outcomes:
            return {}
        
        total_cost = sum(o.cost for o in outcomes)
        successful_outcomes = [o for o in outcomes if o.outcome == OutcomeType.SUCCESS]
        
        if successful_outcomes:
            avg_cost_success = sum(o.cost for o in successful_outcomes) / len(successful_outcomes)
        else:
            avg_cost_success = 0
        
        failed_outcomes = [o for o in outcomes if o.outcome == OutcomeType.FAILURE]
        wasted_cost = sum(o.cost for o in failed_outcomes)
        
        return {
            "total_cost": round(total_cost, 2),
            "avg_cost_per_success": round(avg_cost_success, 2),
            "wasted_on_failures": round(wasted_cost, 2),
            "efficiency_ratio": round(len(successful_outcomes) / len(outcomes), 3) if outcomes else 0,
            "potential_savings": round(wasted_cost * 0.5, 2)  # Estimate 50% of failures preventable
        }
    
    def _analyze_quality(self, agent_id: str) -> Dict[str, Any]:
        """Analyze output quality trends"""
        outcomes = self.tracker.get_recent_outcomes(agent_id=agent_id, limit=100)
        
        if not outcomes:
            return {}
        
        quality_scores = [o.quality_score for o in outcomes if o.quality_score > 0]
        
        if not quality_scores:
            return {"message": "No quality scores available"}
        
        avg_quality = sum(quality_scores) / len(quality_scores)
        
        # Check trend (recent vs older)
        if len(quality_scores) >= 20:
            recent_quality = sum(quality_scores[-10:]) / 10
            older_quality = sum(quality_scores[-20:-10]) / 10
            trend = "improving" if recent_quality > older_quality else "declining" if recent_quality < older_quality else "stable"
        else:
            trend = "insufficient_data"
        
        return {
            "average_quality": round(avg_quality, 3),
            "min_quality": round(min(quality_scores), 3),
            "max_quality": round(max(quality_scores), 3),
            "trend": trend,
            "samples": len(quality_scores)
        }
    
    def get_recommendations(self, agent_id: str) -> List[OptimizationRecommendation]:
        """
        Get actionable optimization recommendations for an agent
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            List of OptimizationRecommendation objects
        """
        recommendations = []
        perf = self.tracker.get_agent_performance(agent_id)
        
        if not perf or perf.total_missions < 10:
            return recommendations
        
        # Model recommendation
        model_analysis = self._analyze_model_performance(agent_id)
        if model_analysis and "recommended_model" in model_analysis:
            current_model = max(perf.model_preferences.items(), key=lambda x: x[1])[0] if perf.model_preferences else "unknown"
            recommended_model = model_analysis["recommended_model"]
            
            if recommended_model and recommended_model != current_model:
                recommendations.append(OptimizationRecommendation(
                    agent_id=agent_id,
                    category="model",
                    current_value=current_model,
                    recommended_value=recommended_model,
                    expected_improvement="15-25% better cost/performance ratio",
                    confidence=0.8,
                    reasoning=f"Model {recommended_model} shows better success rate and quality scores"
                ))
        
        # Complexity recommendation
        complexity_analysis = self._analyze_complexity_performance(agent_id)
        if complexity_analysis and "recommended_complexity" in complexity_analysis:
            current_complexity = max(perf.complexity_breakdown.items(), key=lambda x: x[1])[0] if perf.complexity_breakdown else "unknown"
            recommended_complexity = complexity_analysis["recommended_complexity"]
            
            if recommended_complexity and recommended_complexity != current_complexity:
                recommendations.append(OptimizationRecommendation(
                    agent_id=agent_id,
                    category="complexity",
                    current_value=current_complexity,
                    recommended_value=recommended_complexity,
                    expected_improvement="10-20% higher success rate",
                    confidence=0.75,
                    reasoning=f"Complexity level '{recommended_complexity}' has highest success rate for this agent"
                ))
        
        # Cost optimization
        if perf.avg_cost_per_mission > 5.0:
            recommendations.append(OptimizationRecommendation(
                agent_id=agent_id,
                category="cost",
                current_value=round(perf.avg_cost_per_mission, 2),
                recommended_value=3.0,
                expected_improvement="40% cost reduction",
                confidence=0.7,
                reasoning="Consider using more efficient models or reducing token usage"
            ))
        
        # Quality improvement
        if perf.average_quality < 0.7:
            recommendations.append(OptimizationRecommendation(
                agent_id=agent_id,
                category="quality",
                current_value=round(perf.average_quality, 3),
                recommended_value=0.8,
                expected_improvement="Better output quality",
                confidence=0.65,
                reasoning="Quality scores below threshold - consider better prompts or higher-quality models"
            ))
        
        return recommendations
    
    def auto_optimize(self, agent_id: str) -> AgentConfiguration:
        """
        Automatically generate optimized configuration for an agent
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            AgentConfiguration with optimized settings
        """
        analysis = self.analyze_agent(agent_id)
        
        if "error" in analysis:
            logger.warning(f"Cannot auto-optimize {agent_id}: {analysis['error']}")
            return AgentConfiguration(agent_id=agent_id)
        
        config = AgentConfiguration(agent_id=agent_id)
        
        # Set preferred model
        if "model_analysis" in analysis and "recommended_model" in analysis["model_analysis"]:
            config.preferred_model = analysis["model_analysis"]["recommended_model"]
        
        # Set optimal complexity
        if "complexity_analysis" in analysis and "recommended_complexity" in analysis["complexity_analysis"]:
            config.optimal_complexity = analysis["complexity_analysis"]["recommended_complexity"]
        
        # Set cost limits
        if "cost_analysis" in analysis:
            avg_cost = analysis["cost_analysis"].get("avg_cost_per_success", 5.0)
            config.max_cost_per_mission = avg_cost * 1.2  # 20% buffer
        
        # Set quality threshold
        if "quality_analysis" in analysis:
            avg_quality = analysis["quality_analysis"].get("average_quality", 0.7)
            config.quality_threshold = max(avg_quality * 0.9, 0.6)  # Slightly below average, minimum 0.6
        
        config.last_optimized = datetime.utcnow()
        self._configurations[agent_id] = config
        
        logger.info(f"Auto-optimized configuration for agent {agent_id}")
        return config
    
    def get_configuration(self, agent_id: str) -> Optional[AgentConfiguration]:
        """Get the optimized configuration for an agent"""
        return self._configurations.get(agent_id)
    
    def get_system_insights(self) -> Dict[str, Any]:
        """
        Get system-wide insights across all agents
        
        Returns:
            Dictionary with system-level analytics
        """
        all_performance = self.tracker.get_all_agent_performance()
        
        if not all_performance:
            return {"message": "No performance data available"}
        
        total_missions = sum(p.total_missions for p in all_performance.values())
        total_successes = sum(p.successful_missions for p in all_performance.values())
        total_cost = sum(p.total_cost for p in all_performance.values())
        
        return {
            "total_agents": len(all_performance),
            "total_missions": total_missions,
            "overall_success_rate": round(total_successes / total_missions, 3) if total_missions > 0 else 0,
            "total_cost": round(total_cost, 2),
            "avg_cost_per_mission": round(total_cost / total_missions, 2) if total_missions > 0 else 0,
            "top_performers": [
                {
                    "agent_id": p.agent_id,
                    "success_rate": round(p.success_rate, 3),
                    "missions": p.total_missions
                }
                for p in self.tracker.get_leaderboard(metric="success_rate", limit=5)
            ],
            "complexity_insights": self.tracker.get_complexity_insights()
        }


# Global engine instance
_engine: Optional[AdaptiveLearningEngine] = None


def get_engine() -> AdaptiveLearningEngine:
    """Get the global adaptive learning engine instance"""
    global _engine
    if _engine is None:
        _engine = AdaptiveLearningEngine()
    return _engine
