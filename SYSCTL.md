# OMNIPATH V5.0 - SYSTEM CONTROL GUIDE

**Quick Reference for Managing Omnipath v5.0**

---

## TABLE OF CONTENTS

1. [Installation](#installation)
2. [Navigation Aliases](#navigation-aliases)
3. [Docker Management](#docker-management)
4. [CLI Shortcuts](#cli-shortcuts)
5. [Monitoring & Logs](#monitoring--logs)
6. [Development Tools](#development-tools)
7. [Quick Reference Table](#quick-reference-table)

---

## INSTALLATION

### Add Aliases to Your Shell

**For ZSH:**
```bash
cat omnipath_aliases.zsh >> ~/.zshrc
source ~/.zshrc
```

**For Bash:**
```bash
cat omnipath_aliases.zsh >> ~/.bashrc
source ~/.bashrc
```

### Verify Installation

```bash
op          # Should navigate to project directory
opstatus    # Should show system status
```

---

## NAVIGATION ALIASES

Quick navigation to project directories.

| Alias | Command | Description |
|-------|---------|-------------|
| `op` | `cd ~/projects/omnipath_v2` | Go to project root |
| `opc` | `cd ~/projects/omnipath_v2/cli` | Go to CLI directory |
| `opb` | `cd ~/projects/omnipath_v2/backend` | Go to backend directory |

**Examples:**
```bash
op          # Jump to project
opc         # Jump to CLI
opb         # Jump to backend
```

---

## DOCKER MANAGEMENT

Control all Omnipath services with Docker Compose.

### Core Commands

| Alias | Description | Use When |
|-------|-------------|----------|
| `opup` | Start all services | Starting work session |
| `opdown` | Stop all services | Ending work session |
| `oprestart` | Restart all services | After config changes |
| `oprebuild` | Full rebuild (clean) | After code changes |
| `opps` | Show container status | Checking health |

### Detailed Commands

#### `opup` - Start Services
```bash
opup
```
**What it does:**
- Starts all 7 containers (backend, postgres, redis, nats, prometheus, grafana, jaeger)
- Runs in background (`-d` flag)
- Uses existing images (fast startup)

**When to use:**
- Beginning of work session
- After `opdown`
- After system reboot

---

#### `opdown` - Stop Services
```bash
opdown
```
**What it does:**
- Gracefully stops all containers
- Preserves data volumes
- Frees up ports

**When to use:**
- End of work session
- Before system maintenance
- To free up resources

---

#### `oprestart` - Restart Services
```bash
oprestart
```
**What it does:**
- Restarts all containers
- Keeps existing images
- Preserves data

**When to use:**
- After changing .env file
- After config updates
- When services are unresponsive

---

#### `oprebuild` - Full Rebuild
```bash
oprebuild
```
**What it does:**
1. Stops all containers
2. Removes containers
3. Rebuilds images from scratch (no cache)
4. Starts fresh containers

**When to use:**
- After pulling new code
- After changing Dockerfile
- When fixing persistent issues
- After dependency updates

**Warning:** Takes 1-2 minutes to complete.

---

#### `opps` - Container Status
```bash
opps
```
**Output example:**
```
NAME                  STATUS          PORTS
omnipath-backend      Up 5 minutes    0.0.0.0:8000->8000/tcp
omnipath-postgres     Up 5 minutes    0.0.0.0:5432->5432/tcp
omnipath-redis        Up 5 minutes    0.0.0.0:6379->6379/tcp
omnipath-nats         Up 5 minutes    0.0.0.0:4222->4222/tcp
omnipath-prometheus   Up 5 minutes    0.0.0.0:9090->9090/tcp
omnipath-grafana      Up 5 minutes    0.0.0.0:3000->3000/tcp
omnipath-jaeger       Up 5 minutes    0.0.0.0:16686->16686/tcp
```

**When to use:**
- Verifying all services are running
- Checking uptime
- Debugging startup issues

---

## CLI SHORTCUTS

Interact with Omnipath via command-line interface.

### Core CLI Commands

| Alias | Full Command | Description |
|-------|--------------|-------------|
| `opcli` | `cd ~/projects/omnipath_v2/cli && python omnipath.py` | Base CLI command |
| `opstatus` | `opcli status` | System health check |
| `opagents` | `opcli agent list` | List all agents |
| `opmissions` | `opcli mission list` | List all missions |
| `opleaderboard` | `opcli learning leaderboard` | Top performing agents |
| `opinsights` | `opcli learning insights` | Learning insights |

### Usage Examples

#### Check System Status
```bash
opstatus
```
**Output:**
```
╭──────────────────────── 🚀 System Status ─────────────────────────╮
│ ✅ Omnipath is running                                            │
│                                                                   │
│ Service: Omnipath                                                 │
│ Version: 5.0.0                                                    │
│ Environment: development                                          │
│ API URL: http://localhost:8000                                    │
╰───────────────────────────────────────────────────────────────────╯
```

---

#### List Agents
```bash
opagents
```
**Shows:**
- Agent ID
- Name
- Model
- Status
- Capabilities

---

#### View Leaderboard
```bash
opleaderboard
```
**Shows:**
- Top 10 agents by performance
- Success rates
- Average costs
- Quality scores

---

## MONITORING & LOGS

Track system behavior and debug issues.

### Log Commands

| Alias | Description | Use Case |
|-------|-------------|----------|
| `oplogs` | Follow all container logs | General monitoring |
| `oplogs-backend` | Follow backend logs only | Debug API issues |
| `oplogs-grafana` | Follow Grafana logs | Debug dashboards |
| `oplogs-postgres` | Follow database logs | Debug data issues |

### Usage Examples

#### Watch All Logs
```bash
oplogs
```
**Press Ctrl+C to stop**

---

#### Watch Backend Only
```bash
oplogs-backend
```
**Useful for:**
- Debugging API errors
- Watching mission execution
- Monitoring performance

---

### Health Check Commands

| Alias | Description | Output |
|-------|-------------|--------|
| `ophealth` | API health check | JSON health status |
| `opmetrics` | Prometheus metrics | First 50 metrics |

#### Check API Health
```bash
ophealth
```
**Output:**
```json
{
  "status": "ok",
  "service": "Omnipath",
  "version": "5.0.0",
  "environment": "development",
  "observability": {
    "opentelemetry": true,
    "prometheus": true
  }
}
```

---

#### View Metrics
```bash
opmetrics
```
**Shows:**
- Mission counts
- Success rates
- LLM API calls
- HTTP requests
- System health

---

### Web UI Access

| Alias | URL | Description |
|-------|-----|-------------|
| `opgrafana` | http://localhost:3000 | Open Grafana dashboards |
| `opapi` | http://localhost:8000/docs | Open API documentation |
| `opjaeger` | http://localhost:16686 | Open Jaeger tracing UI |
| `opprom` | http://localhost:9090 | Open Prometheus UI |

**Note:** These use `open` (macOS) or `xdg-open` (Linux). Adjust if needed.

---

## DEVELOPMENT TOOLS

Tools for development and debugging.

### Git Shortcuts

| Alias | Command | Description |
|-------|---------|-------------|
| `opgit` | `cd ~/projects/omnipath_v2 && git status` | Check git status |
| `oppull` | `git pull origin v5.0-rewrite` | Pull latest code |
| `oppush` | `git push origin v5.0-rewrite` | Push changes |

---

### Testing & Cleanup

| Alias | Command | Description |
|-------|---------|-------------|
| `optest` | `pytest tests/ -v` | Run test suite |
| `opclean` | Remove `__pycache__` | Clean Python cache |

#### Run Tests
```bash
optest
```

#### Clean Cache
```bash
opclean
```
**Use when:**
- After switching branches
- Before rebuilding
- When seeing import errors

---

### Advanced Functions

#### Execute Command in Backend Container
```bash
opexec <command>
```
**Examples:**
```bash
opexec ls -la /app/backend
opexec python -c "import sys; print(sys.version)"
opexec pip list
```

---

#### Connect to PostgreSQL
```bash
opsql
```
**Opens:** PostgreSQL shell as `omnipath` user

**Example queries:**
```sql
\dt                                    -- List tables
SELECT * FROM agents;                  -- View agents
SELECT * FROM missions LIMIT 10;       -- View missions
SELECT COUNT(*) FROM performance_outcomes; -- Count outcomes
\q                                     -- Quit
```

---

#### Connect to Redis
```bash
opredis
```
**Opens:** Redis CLI

**Example commands:**
```redis
KEYS *                  -- List all keys
GET key_name            -- Get value
FLUSHALL                -- Clear all data (careful!)
exit                    -- Quit
```

---

## QUICK REFERENCE TABLE

### Most Used Commands

| Task | Command | Frequency |
|------|---------|-----------|
| Start system | `opup` | Daily |
| Check status | `opstatus` | Often |
| View logs | `oplogs-backend` | When debugging |
| Open Grafana | `opgrafana` | Daily |
| Check health | `ophealth` | Often |
| Stop system | `opdown` | Daily |

---

### Workflow Examples

#### Morning Startup
```bash
op              # Go to project
opup            # Start services
sleep 30        # Wait for startup
opstatus        # Verify running
opgrafana       # Open dashboards
```

---

#### After Pulling Code
```bash
op              # Go to project
oppull          # Pull latest
opclean         # Clean cache
oprebuild       # Rebuild everything
opstatus        # Verify working
```

---

#### Debugging Issues
```bash
opps            # Check container status
ophealth        # Check API health
oplogs-backend  # View backend logs
opsql           # Check database
opmetrics       # View metrics
```

---

#### End of Day
```bash
opgit           # Check uncommitted changes
oppush          # Push if needed
opdown          # Stop services
```

---

## TROUBLESHOOTING

### Common Issues

#### "Port already in use"
```bash
opdown          # Stop Omnipath
lsof -i :8000   # Find process using port
kill -9 <PID>   # Kill the process
opup            # Restart
```

---

#### "Container won't start"
```bash
oplogs          # Check error messages
opdown          # Stop everything
opclean         # Clean cache
oprebuild       # Full rebuild
```

---

#### "API returns 500 errors"
```bash
oplogs-backend  # Check backend logs
ophealth        # Verify backend is up
opsql           # Check database connection
```

---

#### "Dashboards not loading"
```bash
oplogs-grafana  # Check Grafana logs
docker restart omnipath-grafana
opgrafana       # Open browser
```

---

#### "Out of sync with GitHub"
```bash
op              # Go to project
git stash       # Save local changes
oppull          # Pull latest
git stash pop   # Restore changes
oprebuild       # Rebuild
```

---

## CUSTOMIZATION

### Add Your Own Aliases

Edit your `~/.zshrc` and add:

```bash
# Custom Omnipath aliases
alias opmycommand='cd ~/projects/omnipath_v2 && <your-command>'
```

Then reload:
```bash
source ~/.zshrc
```

---

### Change Project Path

If your project is in a different location, edit all aliases:

```bash
# Find and replace in ~/.zshrc
# Change: ~/projects/omnipath_v2
# To: /your/custom/path
```

---

## TIPS & TRICKS

### 1. Chain Commands
```bash
op && opup && sleep 30 && opstatus
```

### 2. Watch Logs in Real-Time
```bash
oplogs-backend | grep "ERROR"
```

### 3. Quick Health Check Loop
```bash
watch -n 5 'curl -s http://localhost:8000/health | jq'
```

### 4. Export Metrics
```bash
opmetrics > metrics_$(date +%Y%m%d).txt
```

### 5. Backup Database
```bash
docker exec omnipath-postgres pg_dump -U omnipath omnipath > backup.sql
```

---

## SUPPORT

**Issues?** Check:
1. `opps` - Are all containers running?
2. `ophealth` - Is API responding?
3. `oplogs-backend` - Any errors?
4. GitHub Issues: github.com/1devteam/onmiapath_v2/issues

---

**Omnipath v5.0 System Control - Built with Pride** 🎯
