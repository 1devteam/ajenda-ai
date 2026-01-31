# Omnipath v5.0 Quick Start Guide

Hey! Your Omnipath v5.0 is ready! Here's how to get started (explained like you're 12):

## What's New in v5.0?

Think of v5.0 as giving your agents superpowers:

1. **CLI Tool** - Like a remote control for your agents (type commands instead of clicking)
2. **Meta-Learning** - Agents that learn from mistakes and get smarter over time
3. **Grafana Dashboards** - Pretty graphs showing how your agents are doing
4. **Event Bus** - A super-fast messaging system so parts of your app can talk to each other
5. **Observability** - Like security cameras that show you what's happening inside your system

## Step 1: Pull the New Code

```bash
cd /home/inmoa/projects/omnipath_v2
git pull origin main
```

You should see:
- `cli/` folder (the new CLI tool)
- `grafana/` folder (the dashboards)
- `backend/meta_learning/` folder (the learning system)
- `V5_README.md` (full documentation)

## Step 2: Install New Dependencies

```bash
# Install the new Python packages
pip install -r requirements-v5.txt

# Or install them one by one:
pip install nats-py opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp opentelemetry-instrumentation-fastapi
```

## Step 3: Restart Your Docker Containers

```bash
# Stop everything
docker-compose -f docker-compose.v3.yml down

# Start everything fresh
docker-compose -f docker-compose.v3.yml up -d

# Check that everything is running
docker-compose -f docker-compose.v3.yml ps
```

You should see all these containers running:
- omnipath-backend ✓
- omnipath-postgres ✓
- omnipath-redis ✓
- omnipath-nats ✓
- omnipath-jaeger ✓
- omnipath-prometheus ✓
- omnipath-grafana ✓

## Step 4: Try the CLI

```bash
# Go to the CLI folder
cd cli

# Install CLI dependencies
pip install -r requirements.txt

# Make it executable
chmod +x omnipath.py

# Test it!
./omnipath.py status
```

If it works, you'll see: "✅ Omnipath is running"

### Cool CLI Commands to Try:

```bash
# See all commands
./omnipath.py --help

# Create an agent
./omnipath.py agent create --name "TestAgent" --model gpt-4

# List agents
./omnipath.py agent list

# Check economy balance
./omnipath.py economy balance

# See system status
./omnipath.py status
```

## Step 5: Check Out Grafana Dashboards

Open your browser and go to: **http://localhost:3000**

- Username: `admin`
- Password: `admin`

You'll see 3 dashboards:
1. **Agent Economy** - Shows credits, balances, transactions
2. **Mission Performance** - Shows how missions are doing
3. **System Health** - Shows if everything is working

(They might be empty at first - they'll fill up as you use the system!)

## Step 6: Try Meta-Learning

The meta-learning system tracks how your agents perform and helps them improve.

### Using the API:

```bash
# Get performance metrics for an agent
curl http://localhost:8000/api/v1/meta-learning/performance/agent-123

# Get learning insights (what the agent learned)
curl http://localhost:8000/api/v1/meta-learning/insights/agent-123

# Auto-tune an agent (let the system optimize it)
curl -X POST http://localhost:8000/api/v1/meta-learning/auto-tune/agent-123

# See the leaderboard (top performing agents)
curl http://localhost:8000/api/v1/meta-learning/leaderboard
```

### How It Works:

1. Every time a mission completes, the system records:
   - Did it succeed or fail?
   - How long did it take?
   - How much did it cost?
   - What settings were used?

2. After 10+ missions, the system starts learning:
   - Which model works best?
   - What temperature is optimal?
   - Is the agent improving over time?

3. You can ask for recommendations or let it auto-tune!

## Step 7: Check Observability

### Jaeger (Request Tracing)

Open: **http://localhost:16686**

This shows you the "journey" of each request through your system. Like a GPS tracker for your API calls!

### Prometheus (Metrics)

Open: **http://localhost:9090**

This collects all the performance numbers. Grafana uses this data for the dashboards.

## What to Do Next

### Option 1: Play with the CLI
```bash
cd cli
./omnipath.py agent create --name "MyFirstAgent" --model gpt-4
./omnipath.py mission launch --agent-id <id> --objective "Test mission"
./omnipath.py economy balance
```

### Option 2: Integrate Meta-Learning

Add this to your mission execution code:

```python
from backend.meta_learning import get_tracker, MissionOutcome
from datetime import datetime

# After a mission completes:
outcome = MissionOutcome(
    mission_id=mission_id,
    agent_id=agent_id,
    objective="Your mission objective",
    status="completed",  # or "failed"
    duration_seconds=45.2,
    tokens_used=1500,
    cost=0.03,
    quality_score=0.85,
    timestamp=datetime.now(),
    context={"model": "gpt-4", "temperature": 0.7}
)

tracker = get_tracker()
tracker.record_outcome(outcome)
```

### Option 3: Watch the Dashboards

1. Open Grafana: http://localhost:3000
2. Run some missions
3. Watch the graphs update in real-time!

## Troubleshooting

### "NATS connection failed"
Don't worry! The system automatically falls back to a local mode. Everything still works.

### "Grafana dashboards are empty"
They need data first. Run some missions and they'll fill up!

### "CLI command not found"
Make sure you're in the `cli/` folder and ran `chmod +x omnipath.py`

### "Import error: nats-py"
Install it: `pip install nats-py`

## Need Help?

1. Check the full docs: `V5_README.md`
2. Check specific docs:
   - CLI: `cli/README.md`
   - Meta-Learning: `backend/meta_learning/README.md`
   - Grafana: `grafana/README.md`
3. Check API docs: http://localhost:8000/docs

## Summary

You now have:
- ✅ CLI tool for managing agents
- ✅ Meta-learning system that makes agents smarter
- ✅ Grafana dashboards for visualization
- ✅ Event bus for messaging
- ✅ OpenTelemetry for tracing

Everything is backward compatible - your v4.5 code still works!

**Welcome to v5.0! 🚀**
