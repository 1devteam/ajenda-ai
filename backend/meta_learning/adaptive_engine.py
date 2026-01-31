"""
Adaptive Learning Engine
Automatically adjusts agent parameters based on performance data
"""
from typing import Dict, Optional, Tuple
from datetime import timedelta
import statistics
from .performance_tracker import PerformanceTracker, get_tracker


class AdaptiveEngine:
    """
    Automatically tunes agent parameters based on learning
    
    Think of this as an auto-pilot that adjusts the controls
    to get better results over time.
    """
    
    def __init__(self, tracker: Optional[PerformanceTracker] = None):
        self.tracker = tracker or get_tracker()
        
        # Learning rates - how fast we adapt
        self.learning_rate = 0.1
        
        # Default configurations
        self.default_config = {
            'model': 'gpt-4',
            'temperature': 0.7,
            'max_tokens': 2000,
            'timeout_seconds': 300
        }
    
    def get_optimal_config(self, agent_id: str, 
                          mission_type: Optional[str] = None) -> Dict:
        """
        Get the optimal configuration for an agent based on learning
        
        This is like a coach saying: "Based on your past games, 
        here's the best strategy for you"
        """
        # Start with defaults
        config = self.default_config.copy()
        
        # Get performance insights
        insights = self.tracker.get_learning_insights(agent_id)
        
        if 'patterns' not in insights:
            # Not enough data, return defaults
            return config
        
        patterns = insights['patterns']
        
        # Apply learned optimizations
        if 'best_model' in patterns:
            config['model'] = patterns['best_model']['model']
        
        if 'optimal_temperature' in patterns:
            config['temperature'] = patterns['optimal_temperature']
        
        # Get configuration comparison
        comparison = self.tracker.compare_configurations(agent_id)
        
        if 'model_comparison' in comparison and comparison['model_comparison']:
            # Find the model with best success rate and reasonable cost
            models = comparison['model_comparison']
            
            # Score models: success_rate * 0.7 + (1 - normalized_cost) * 0.3
            if models:
                max_cost = max(m['avg_cost'] for m in models.values())
                
                scored_models = {}
                for model, stats in models.items():
                    if max_cost > 0:
                        cost_score = 1 - (stats['avg_cost'] / max_cost)
                    else:
                        cost_score = 1.0
                    
                    total_score = (stats['success_rate'] * 0.7 + 
                                 cost_score * 0.3)
                    scored_models[model] = total_score
                
                best_model = max(scored_models.items(), key=lambda x: x[1])
                config['model'] = best_model[0]
        
        return config
    
    def should_adapt(self, agent_id: str, min_missions: int = 10) -> bool:
        """
        Check if we have enough data to start adapting
        
        Like waiting until you have enough practice before trying advanced moves
        """
        perf = self.tracker.get_agent_performance(agent_id)
        return perf['total_missions'] >= min_missions
    
    def suggest_experiment(self, agent_id: str) -> Optional[Dict]:
        """
        Suggest a configuration to try as an experiment
        
        This is like a scientist saying: "Let's try this and see what happens"
        """
        if not self.should_adapt(agent_id, min_missions=5):
            return None
        
        # Get current best config
        current_config = self.get_optimal_config(agent_id)
        
        # Get performance with current config
        perf = self.tracker.get_agent_performance(
            agent_id, 
            time_window=timedelta(days=7)
        )
        
        suggestions = []
        
        # Experiment 1: Try different temperature
        if perf['success_rate'] < 0.8:
            # If success rate is low, try adjusting temperature
            current_temp = current_config['temperature']
            
            if current_temp > 0.5:
                # Try lower temperature for more deterministic output
                suggestions.append({
                    'type': 'temperature_adjustment',
                    'config': {**current_config, 'temperature': current_temp - 0.1},
                    'reason': 'Lower temperature may improve consistency'
                })
            else:
                # Try higher temperature for more creativity
                suggestions.append({
                    'type': 'temperature_adjustment',
                    'config': {**current_config, 'temperature': current_temp + 0.1},
                    'reason': 'Higher temperature may improve creativity'
                })
        
        # Experiment 2: Try different model
        current_model = current_config['model']
        alternative_models = ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo', 'claude-3-opus']
        
        if current_model in alternative_models:
            alternative_models.remove(current_model)
        
        if alternative_models and perf['total_missions'] >= 10:
            suggestions.append({
                'type': 'model_experiment',
                'config': {**current_config, 'model': alternative_models[0]},
                'reason': f'Try {alternative_models[0]} to compare performance'
            })
        
        # Return the first suggestion
        return suggestions[0] if suggestions else None
    
    def calculate_improvement(self, agent_id: str, 
                            window_days: int = 7) -> Dict:
        """
        Calculate how much the agent has improved over time
        
        Like comparing your test scores from the beginning of the year
        to now - are you getting better?
        """
        all_perf = self.tracker.get_agent_performance(agent_id)
        recent_perf = self.tracker.get_agent_performance(
            agent_id,
            time_window=timedelta(days=window_days)
        )
        
        if all_perf['total_missions'] < 10:
            return {
                'status': 'insufficient_data',
                'message': 'Need at least 10 missions to calculate improvement'
            }
        
        # Calculate improvement metrics
        success_rate_change = (recent_perf['success_rate'] - 
                              all_perf['success_rate'])
        
        duration_change = (all_perf['avg_duration'] - 
                          recent_perf['avg_duration'])
        
        cost_change = (all_perf['avg_cost'] - 
                      recent_perf['avg_cost'])
        
        # Determine overall trend
        improvements = []
        regressions = []
        
        if success_rate_change > 0.05:
            improvements.append(f"Success rate improved by {success_rate_change*100:.1f}%")
        elif success_rate_change < -0.05:
            regressions.append(f"Success rate decreased by {abs(success_rate_change)*100:.1f}%")
        
        if duration_change > 10:
            improvements.append(f"Missions are {duration_change:.1f}s faster")
        elif duration_change < -10:
            regressions.append(f"Missions are {abs(duration_change):.1f}s slower")
        
        if cost_change > 0.01:
            improvements.append(f"Cost reduced by ${cost_change:.3f} per mission")
        elif cost_change < -0.01:
            regressions.append(f"Cost increased by ${abs(cost_change):.3f} per mission")
        
        return {
            'agent_id': agent_id,
            'window_days': window_days,
            'metrics': {
                'success_rate_change': round(success_rate_change, 3),
                'duration_change_seconds': round(duration_change, 2),
                'cost_change': round(cost_change, 4)
            },
            'improvements': improvements,
            'regressions': regressions,
            'overall_trend': 'improving' if len(improvements) > len(regressions) else 
                           'declining' if len(regressions) > len(improvements) else 
                           'stable'
        }
    
    def auto_tune(self, agent_id: str, aggressive: bool = False) -> Tuple[Dict, str]:
        """
        Automatically tune agent configuration based on learning
        
        This is the "autopilot" - it makes decisions for you based on data
        
        Args:
            agent_id: The agent to tune
            aggressive: If True, makes bigger changes; if False, makes conservative changes
        
        Returns:
            (new_config, explanation)
        """
        if not self.should_adapt(agent_id):
            return (
                self.default_config.copy(),
                "Not enough data yet - using default configuration"
            )
        
        # Get optimal config based on learning
        optimal_config = self.get_optimal_config(agent_id)
        
        # Get performance metrics
        perf = self.tracker.get_agent_performance(
            agent_id,
            time_window=timedelta(days=7)
        )
        
        explanation_parts = []
        
        # Adjust based on success rate
        if perf['success_rate'] < 0.7:
            # Low success rate - try more conservative settings
            if optimal_config['temperature'] > 0.3:
                optimal_config['temperature'] = max(0.3, optimal_config['temperature'] - 0.2)
                explanation_parts.append("Reduced temperature for more consistent output")
        
        elif perf['success_rate'] > 0.9:
            # High success rate - can try more aggressive settings
            if aggressive and optimal_config['temperature'] < 0.9:
                optimal_config['temperature'] = min(0.9, optimal_config['temperature'] + 0.1)
                explanation_parts.append("Increased temperature for more creative output")
        
        # Adjust based on cost
        if perf['avg_cost'] > 0.5:
            # High cost - suggest cheaper model
            if optimal_config['model'] == 'gpt-4':
                optimal_config['model'] = 'gpt-4-turbo'
                explanation_parts.append("Switched to GPT-4 Turbo to reduce costs")
        
        # Adjust timeout based on duration
        if perf['avg_duration'] > 200:
            optimal_config['timeout_seconds'] = 600
            explanation_parts.append("Increased timeout for longer missions")
        elif perf['avg_duration'] < 60:
            optimal_config['timeout_seconds'] = 180
            explanation_parts.append("Reduced timeout for faster missions")
        
        explanation = "; ".join(explanation_parts) if explanation_parts else \
                     "Using optimal configuration based on historical performance"
        
        return (optimal_config, explanation)


# Global adaptive engine instance
_engine = AdaptiveEngine()


def get_engine() -> AdaptiveEngine:
    """Get the global adaptive engine instance"""
    return _engine
