# Omnipath CLI

Beautiful command-line interface for Omnipath v5.0 - Multi-Agent AI Orchestration Platform

## Features

- 🎨 **Beautiful Terminal UI** - Rich colors, tables, and panels
- 👤 **Agent Management** - List, view, and monitor agents
- 🎯 **Mission Control** - Track and manage missions
- 💰 **Economy Monitoring** - Check balances and transactions
- 🧠 **Meta-Learning Insights** - Performance analytics and optimization
- 🏆 **Leaderboards** - See top performing agents
- ⚙️ **Auto-Optimization** - AI-powered agent tuning

## Installation

```bash
cd cli
pip install -r requirements.txt
chmod +x omnipath.py
```

## Configuration

Set your API endpoint:

```bash
./omnipath.py config --api-url http://localhost:8000
```

View current configuration:

```bash
./omnipath.py config --show
```

## Usage

### System Status

Check if Omnipath is running:

```bash
./omnipath.py status
```

### Agent Commands

List all agents:

```bash
./omnipath.py agent list
```

Show agent details:

```bash
./omnipath.py agent show <agent-id>
```

View agent performance:

```bash
./omnipath.py agent performance <agent-id>
```

### Mission Commands

List missions:

```bash
./omnipath.py mission list
```

Filter by status:

```bash
./omnipath.py mission list --status completed
```

### Economy Commands

Check agent balance:

```bash
./omnipath.py economy balance --agent <agent-id>
```

View transactions:

```bash
./omnipath.py economy transactions --agent <agent-id> --limit 20
```

### Learning Commands

View leaderboard:

```bash
./omnipath.py learning leaderboard
```

Rank by different metrics:

```bash
./omnipath.py learning leaderboard --metric avg_cost_per_mission
```

Get learning insights:

```bash
./omnipath.py learning insights <agent-id>
```

Auto-optimize agent:

```bash
./omnipath.py learning optimize <agent-id>
```

## Available Metrics for Leaderboard

- `success_rate` - Mission success percentage
- `avg_cost_per_mission` - Cost efficiency
- `avg_duration_per_mission` - Speed
- `average_quality` - Output quality

## Examples

```bash
# Quick system check
./omnipath.py status

# See top 5 agents by success rate
./omnipath.py learning leaderboard --limit 5

# Optimize an agent
./omnipath.py learning optimize agent-123

# Monitor recent missions
./omnipath.py mission list --limit 50

# Check economy activity
./omnipath.py economy transactions --limit 100
```

## Tips

- Use `--help` on any command to see all options
- Agent IDs can be shortened (first 8 characters work)
- All tables support scrolling in your terminal
- Configuration is saved in `~/.omnipath/config.json`

## Requirements

- Python 3.8+
- Omnipath v5.0 backend running
- Network access to Omnipath API

## Troubleshooting

**Connection refused:**
- Check if backend is running: `docker ps`
- Verify API URL: `./omnipath.py config --show`
- Test health endpoint: `curl http://localhost:8000/health`

**Command not found:**
- Make script executable: `chmod +x omnipath.py`
- Or run with Python: `python3 omnipath.py status`

**Import errors:**
- Install dependencies: `pip install -r requirements.txt`
- Check Python version: `python3 --version` (need 3.8+)
