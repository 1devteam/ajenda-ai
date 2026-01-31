"""
Performance Tracker for Meta-Learning System
Tracks agent performance metrics and mission outcomes for learning
"""
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import json
from collections import defaultdict
import statistics


@dataclass
class MissionOutcome:
    """Record of a mission outcome for learning"""
    mission_id: str
    agent_id: str
    objective: str
    status: str  # completed, failed, timeout
    duration_seconds: float
    tokens_used: int
    cost: float
    quality_score: Optional[float]  # 0-1 rating of output quality
    timestamp: datetime
    context: Dict  # Additional context (model, temperature, etc.)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'MissionOutcome':
        """Create from dictionary"""
        data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        return cls(**data)


class PerformanceTracker:
    """
    Tracks agent performance over time for meta-learning
    
    This is like a report card for each agent - it remembers:
    - How many missions succeeded vs failed
    - How long missions take
    - How much they cost
    - What settings work best
    """
    
    def __init__(self):
        self.outcomes: List[MissionOutcome] = []
        self.agent_stats: Dict[str, Dict] = defaultdict(lambda: {
            'total_missions': 0,
            'successful_missions': 0,
            'failed_missions': 0,
            'total_duration': 0.0,
            'total_cost': 0.0,
            'total_tokens': 0,
            'quality_scores': []
        })
    
    def record_outcome(self, outcome: MissionOutcome):
        """Record a mission outcome"""
        self.outcomes.append(outcome)
        
        # Update agent statistics
        stats = self.agent_stats[outcome.agent_id]
        stats['total_missions'] += 1
        
        if outcome.status == 'completed':
            stats['successful_missions'] += 1
        elif outcome.status == 'failed':
            stats['failed_missions'] += 1
        
        stats['total_duration'] += outcome.duration_seconds
        stats['total_cost'] += outcome.cost
        stats['total_tokens'] += outcome.tokens_used
        
        if outcome.quality_score is not None:
            stats['quality_scores'].append(outcome.quality_score)
    
    def get_agent_performance(self, agent_id: str, 
                             time_window: Optional[timedelta] = None) -> Dict:
        """
        Get performance metrics for an agent
        
        Like getting a student's grades - shows how well they're doing
        """
        if time_window:
            cutoff = datetime.now() - time_window
            outcomes = [o for o in self.outcomes 
                       if o.agent_id == agent_id and o.timestamp >= cutoff]
        else:
            outcomes = [o for o in self.outcomes if o.agent_id == agent_id]
        
        if not outcomes:
            return {
                'agent_id': agent_id,
                'total_missions': 0,
                'success_rate': 0.0,
                'avg_duration': 0.0,
                'avg_cost': 0.0,
                'avg_quality': 0.0
            }
        
        successful = sum(1 for o in outcomes if o.status == 'completed')
        total = len(outcomes)
        
        quality_scores = [o.quality_score for o in outcomes 
                         if o.quality_score is not None]
        
        return {
            'agent_id': agent_id,
            'total_missions': total,
            'successful_missions': successful,
            'failed_missions': total - successful,
            'success_rate': successful / total if total > 0 else 0.0,
            'avg_duration': statistics.mean([o.duration_seconds for o in outcomes]),
            'avg_cost': statistics.mean([o.cost for o in outcomes]),
            'avg_tokens': statistics.mean([o.tokens_used for o in outcomes]),
            'avg_quality': statistics.mean(quality_scores) if quality_scores else None,
            'total_cost': sum(o.cost for o in outcomes),
            'time_window': str(time_window) if time_window else 'all_time'
        }
    
    def get_best_performing_agents(self, top_n: int = 10, 
                                   metric: str = 'success_rate') -> List[Dict]:
        """
        Get the top performing agents
        
        Like a leaderboard - who's the best at their job?
        """
        agent_performances = []
        for agent_id in self.agent_stats.keys():
            perf = self.get_agent_performance(agent_id)
            if perf['total_missions'] >= 3:  # Need at least 3 missions
                agent_performances.append(perf)
        
        # Sort by metric
        agent_performances.sort(key=lambda x: x.get(metric, 0), reverse=True)
        return agent_performances[:top_n]
    
    def get_learning_insights(self, agent_id: str) -> Dict:
        """
        Get actionable insights for improving agent performance
        
        This is like a teacher giving feedback: "You're good at X, but need to work on Y"
        """
        outcomes = [o for o in self.outcomes if o.agent_id == agent_id]
        
        if len(outcomes) < 5:
            return {
                'agent_id': agent_id,
                'insight': 'Not enough data yet - need at least 5 missions',
                'recommendations': []
            }
        
        # Analyze patterns
        successful = [o for o in outcomes if o.status == 'completed']
        failed = [o for o in outcomes if o.status == 'failed']
        
        insights = {
            'agent_id': agent_id,
            'total_missions': len(outcomes),
            'patterns': {},
            'recommendations': []
        }
        
        # Pattern: Success rate by model
        if successful:
            models_used = defaultdict(lambda: {'success': 0, 'total': 0})
            for outcome in outcomes:
                model = outcome.context.get('model', 'unknown')
                models_used[model]['total'] += 1
                if outcome.status == 'completed':
                    models_used[model]['success'] += 1
            
            best_model = max(models_used.items(), 
                           key=lambda x: x[1]['success'] / x[1]['total'] 
                           if x[1]['total'] > 0 else 0)
            
            insights['patterns']['best_model'] = {
                'model': best_model[0],
                'success_rate': best_model[1]['success'] / best_model[1]['total']
            }
            insights['recommendations'].append(
                f"Use model '{best_model[0]}' - it has the highest success rate"
            )
        
        # Pattern: Optimal temperature
        if successful:
            temps = [o.context.get('temperature', 0.7) for o in successful]
            avg_temp = statistics.mean(temps)
            insights['patterns']['optimal_temperature'] = round(avg_temp, 2)
            insights['recommendations'].append(
                f"Optimal temperature appears to be around {avg_temp:.2f}"
            )
        
        # Pattern: Cost efficiency
        if successful:
            cost_per_success = [o.cost for o in successful]
            avg_cost = statistics.mean(cost_per_success)
            insights['patterns']['avg_cost_per_success'] = round(avg_cost, 4)
            
            if avg_cost > 0.5:
                insights['recommendations'].append(
                    "Consider using a cheaper model - costs are high"
                )
        
        # Pattern: Duration trends
        if len(outcomes) >= 10:
            recent = outcomes[-5:]
            older = outcomes[-10:-5]
            
            recent_duration = statistics.mean([o.duration_seconds for o in recent])
            older_duration = statistics.mean([o.duration_seconds for o in older])
            
            if recent_duration < older_duration * 0.8:
                insights['recommendations'].append(
                    "Performance is improving - missions are getting faster!"
                )
            elif recent_duration > older_duration * 1.2:
                insights['recommendations'].append(
                    "Performance is declining - missions are taking longer"
                )
        
        return insights
    
    def compare_configurations(self, agent_id: str) -> Dict:
        """
        Compare different configuration settings to find what works best
        
        Like A/B testing - which settings produce the best results?
        """
        outcomes = [o for o in self.outcomes if o.agent_id == agent_id]
        
        if len(outcomes) < 5:
            return {'message': 'Not enough data for comparison'}
        
        # Group by configuration parameters
        by_model = defaultdict(list)
        by_temperature = defaultdict(list)
        
        for outcome in outcomes:
            model = outcome.context.get('model', 'unknown')
            temp = outcome.context.get('temperature', 0.7)
            
            by_model[model].append(outcome)
            by_temperature[round(temp, 1)].append(outcome)
        
        # Calculate success rates
        model_comparison = {}
        for model, outcomes_list in by_model.items():
            if len(outcomes_list) >= 2:
                success_rate = sum(1 for o in outcomes_list if o.status == 'completed') / len(outcomes_list)
                avg_cost = statistics.mean([o.cost for o in outcomes_list])
                avg_duration = statistics.mean([o.duration_seconds for o in outcomes_list])
                
                model_comparison[model] = {
                    'success_rate': round(success_rate, 3),
                    'avg_cost': round(avg_cost, 4),
                    'avg_duration': round(avg_duration, 2),
                    'sample_size': len(outcomes_list)
                }
        
        temp_comparison = {}
        for temp, outcomes_list in by_temperature.items():
            if len(outcomes_list) >= 2:
                success_rate = sum(1 for o in outcomes_list if o.status == 'completed') / len(outcomes_list)
                
                temp_comparison[temp] = {
                    'success_rate': round(success_rate, 3),
                    'sample_size': len(outcomes_list)
                }
        
        return {
            'agent_id': agent_id,
            'model_comparison': model_comparison,
            'temperature_comparison': temp_comparison
        }
    
    def export_data(self, filepath: str):
        """Export all performance data to JSON"""
        data = {
            'outcomes': [o.to_dict() for o in self.outcomes],
            'agent_stats': dict(self.agent_stats),
            'exported_at': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    def import_data(self, filepath: str):
        """Import performance data from JSON"""
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        self.outcomes = [MissionOutcome.from_dict(o) for o in data['outcomes']]
        self.agent_stats = defaultdict(lambda: {
            'total_missions': 0,
            'successful_missions': 0,
            'failed_missions': 0,
            'total_duration': 0.0,
            'total_cost': 0.0,
            'total_tokens': 0,
            'quality_scores': []
        }, data['agent_stats'])


# Global tracker instance
_tracker = PerformanceTracker()


def get_tracker() -> PerformanceTracker:
    """Get the global performance tracker instance"""
    return _tracker
