# Meta-Learning System

The meta-learning system enables agents to learn from experience and automatically improve their performance over time.

## Overview

**What is meta-learning?** It's "learning how to learn" - the system tracks agent performance, identifies patterns, and automatically adjusts configurations to optimize results.

Think of it like this:
- **Without meta-learning**: Every mission uses the same settings, regardless of whether they work well
- **With meta-learning**: The system remembers what worked, learns from mistakes, and gets better over time

## Components

### 1. Performance Tracker (`performance_tracker.py`)

Tracks every mission outcome with detailed metrics:
- Success/failure status
- Duration and cost
- Quality scores
- Configuration used (model, temperature, etc.)

**Like a report card** - it remembers everything the agent does.

### 2. Adaptive Engine (`adaptive_engine.py`)

Analyzes performance data and automatically tunes agent configurations:
- Finds optimal model and parameters
- Suggests experiments to try
- Calculates improvement over time
- Auto-tunes settings based on goals

**Like a coach** - it gives advice on how to improve.

### 3. API Routes (`routes/meta_learning.py`)

REST API endpoints for accessing learning insights:
- `/performance/{agent_id}` - Get performance metrics
- `/insights/{agent_id}` - Get actionable recommendations
- `/optimal-config/{agent_id}` - Get best configuration
- `/auto-tune/{agent_id}` - Automatically optimize settings
- `/leaderboard` - See top performing agents

## How It Works

### Step 1: Record Outcomes

Every time a mission completes, record the outcome:

```python
from backend.meta_learning import get_tracker, MissionOutcome
from datetime import datetime

tracker = get_tracker()

outcome = MissionOutcome(
    mission_id="mission-123",
    agent_id="agent-456",
    objective="Analyze market trends",
    status="completed",  # or "failed"
    duration_seconds=45.2,
    tokens_used=1500,
    cost=0.03,
    quality_score=0.85,  # 0-1 rating
    timestamp=datetime.now(),
    context={
        "model": "gpt-4",
        "temperature": 0.7
    }
)

tracker.record_outcome(outcome)
```

### Step 2: Get Insights

After collecting data, get insights:

```python
from backend.meta_learning import get_tracker

tracker = get_tracker()

# Get performance metrics
performance = tracker.get_agent_performance("agent-456")
print(f"Success rate: {performance['success_rate']}")
print(f"Average cost: ${performance['avg_cost']}")

# Get learning insights
insights = tracker.get_learning_insights("agent-456")
print("Recommendations:")
for rec in insights['recommendations']:
    print(f"  - {rec}")
```

### Step 3: Auto-Tune

Let the system optimize automatically:

```python
from backend.meta_learning import get_engine

engine = get_engine()

# Get optimal configuration
config = engine.get_optimal_config("agent-456")
print(f"Best model: {config['model']}")
print(f"Best temperature: {config['temperature']}")

# Auto-tune (makes decisions for you)
new_config, explanation = engine.auto_tune("agent-456", aggressive=False)
print(f"New config: {new_config}")
print(f"Why: {explanation}")
```

## Integration with Missions

To enable meta-learning for missions, integrate it into your mission execution flow:

```python
from backend.meta_learning import get_tracker, get_engine, MissionOutcome
from datetime import datetime
import time

async def execute_mission(mission_id: str, agent_id: str, objective: str):
    # Get optimal configuration
    engine = get_engine()
    config = engine.get_optimal_config(agent_id)
    
    # Execute mission with optimal config
    start_time = time.time()
    
    try:
        result = await run_mission_with_config(
            objective=objective,
            model=config['model'],
            temperature=config['temperature']
        )
        
        duration = time.time() - start_time
        
        # Record successful outcome
        outcome = MissionOutcome(
            mission_id=mission_id,
            agent_id=agent_id,
            objective=objective,
            status="completed",
            duration_seconds=duration,
            tokens_used=result.tokens,
            cost=result.cost,
            quality_score=result.quality,
            timestamp=datetime.now(),
            context=config
        )
        
    except Exception as e:
        duration = time.time() - start_time
        
        # Record failed outcome
        outcome = MissionOutcome(
            mission_id=mission_id,
            agent_id=agent_id,
            objective=objective,
            status="failed",
            duration_seconds=duration,
            tokens_used=0,
            cost=0,
            quality_score=None,
            timestamp=datetime.now(),
            context=config
        )
    
    # Record the outcome for learning
    tracker = get_tracker()
    tracker.record_outcome(outcome)
    
    return result
```

## API Examples

### Get Agent Performance

```bash
curl http://localhost:8000/api/v1/meta-learning/performance/agent-456
```

Response:
```json
{
  "agent_id": "agent-456",
  "total_missions": 25,
  "successful_missions": 22,
  "failed_missions": 3,
  "success_rate": 0.88,
  "avg_duration": 42.5,
  "avg_cost": 0.025,
  "avg_quality": 0.82
}
```

### Get Learning Insights

```bash
curl http://localhost:8000/api/v1/meta-learning/insights/agent-456
```

Response:
```json
{
  "agent_id": "agent-456",
  "total_missions": 25,
  "patterns": {
    "best_model": {
      "model": "gpt-4",
      "success_rate": 0.92
    },
    "optimal_temperature": 0.65
  },
  "recommendations": [
    "Use model 'gpt-4' - it has the highest success rate",
    "Optimal temperature appears to be around 0.65",
    "Performance is improving - missions are getting faster!"
  ]
}
```

### Auto-Tune Agent

```bash
curl -X POST http://localhost:8000/api/v1/meta-learning/auto-tune/agent-456?aggressive=false
```

Response:
```json
{
  "agent_id": "agent-456",
  "new_config": {
    "model": "gpt-4-turbo",
    "temperature": 0.65,
    "max_tokens": 2000,
    "timeout_seconds": 300
  },
  "explanation": "Switched to GPT-4 Turbo to reduce costs; Using optimal configuration based on historical performance",
  "aggressive_mode": false
}
```

### Get Leaderboard

```bash
curl http://localhost:8000/api/v1/meta-learning/leaderboard?top_n=5&metric=success_rate
```

Response:
```json
{
  "metric": "success_rate",
  "top_agents": [
    {
      "agent_id": "agent-789",
      "success_rate": 0.95,
      "total_missions": 50
    },
    {
      "agent_id": "agent-456",
      "success_rate": 0.88,
      "total_missions": 25
    }
  ]
}
```

## Configuration Options

### Learning Rate

Controls how quickly the system adapts:

```python
from backend.meta_learning import get_engine

engine = get_engine()
engine.learning_rate = 0.2  # Higher = faster adaptation (default: 0.1)
```

### Minimum Missions for Adaptation

Set minimum data required before adapting:

```python
# In adaptive_engine.py
def should_adapt(self, agent_id: str, min_missions: int = 10) -> bool:
    # Requires at least 10 missions by default
    # Increase for more conservative adaptation
    # Decrease for faster experimentation
```

### Default Configuration

Set fallback configuration:

```python
engine.default_config = {
    'model': 'gpt-4',
    'temperature': 0.7,
    'max_tokens': 2000,
    'timeout_seconds': 300
}
```

## Metrics Tracked

| Metric | Description | Use Case |
|--------|-------------|----------|
| `success_rate` | % of completed missions | Overall effectiveness |
| `avg_duration` | Average mission time | Efficiency tracking |
| `avg_cost` | Average cost per mission | Budget optimization |
| `avg_quality` | Average quality score | Output quality |
| `total_missions` | Total missions run | Experience level |

## Best Practices

### 1. Always Record Outcomes

Record every mission outcome, even failures. Failures teach the system what doesn't work.

### 2. Use Quality Scores

If possible, rate mission output quality (0-1). This helps the system optimize for quality, not just speed.

### 3. Start Conservative

Use `aggressive=False` for auto-tuning initially. Once you trust the system, enable aggressive mode.

### 4. Monitor Improvement

Regularly check improvement metrics:

```bash
curl http://localhost:8000/api/v1/meta-learning/improvement/agent-456?window_days=7
```

### 5. Export Data Regularly

Back up learning data:

```python
tracker = get_tracker()
tracker.export_data("/path/to/backup.json")
```

### 6. Use Experiments

Try suggested experiments to discover better configurations:

```bash
curl http://localhost:8000/api/v1/meta-learning/experiment/agent-456
```

## Troubleshooting

**"Not enough data yet"**
- Need at least 5-10 missions before learning kicks in
- Keep running missions to build history

**"No improvements detected"**
- May need more varied experiments
- Try different models or temperatures manually
- Check if missions are too similar

**"Performance declining"**
- Review recent configuration changes
- Check for external factors (API issues, etc.)
- Consider reverting to previous optimal config

## Advanced: Custom Learning Algorithms

You can extend the adaptive engine with custom algorithms:

```python
from backend.meta_learning import AdaptiveEngine

class CustomEngine(AdaptiveEngine):
    def get_optimal_config(self, agent_id: str, mission_type=None):
        # Your custom logic here
        config = super().get_optimal_config(agent_id, mission_type)
        
        # Add custom adjustments
        if mission_type == "creative":
            config['temperature'] = 0.9
        elif mission_type == "analytical":
            config['temperature'] = 0.3
        
        return config
```

## Future Enhancements

Planned features for future versions:
- **Multi-agent learning**: Agents learn from each other's experiences
- **Transfer learning**: Apply learning from one task type to another
- **Reinforcement learning**: Use rewards to guide optimization
- **A/B testing framework**: Automated experimentation
- **Anomaly detection**: Identify unusual performance patterns

## License

Part of the Omnipath v5.0 project.
