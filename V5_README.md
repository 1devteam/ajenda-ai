# Omnipath v5.0 - Complete Release

**Built with Pride** by the Omnipath Development Team for Obex Blackvault

---

## 🎯 What's New in v5.0

Omnipath v5.0 is a complete rewrite from v4.5, built properly with production-grade observability, meta-learning intelligence, and beautiful interfaces.

### Core Improvements

**1. Real Observability** 🔍
- OpenTelemetry distributed tracing to Jaeger
- Prometheus metrics for all operations
- HTTP request/response tracking
- System health monitoring
- Performance bottleneck identification

**2. Meta-Learning System** 🧠
- Agents learn from every mission
- Performance tracking and analysis
- Automatic optimization recommendations
- Adaptive configuration tuning
- System-wide intelligence gathering

**3. CLI Interface** 💻
- Beautiful terminal UI with colors and tables
- Agent management commands
- Mission control
- Economy monitoring
- Meta-learning insights
- One-line operations

**4. Grafana Dashboards** 📊
- 3 pre-configured dashboards
- Real-time metrics visualization
- Auto-provisioning (zero setup)
- Beautiful charts and gauges
- 5-second refresh rate

---

## 📦 What's Included

```
omnipath_v2/
├── backend/
│   ├── api/routes/
│   │   └── meta_learning.py          # 15 new API endpoints
│   ├── integrations/observability/
│   │   ├── telemetry.py               # Real OpenTelemetry
│   │   └── prometheus_metrics.py      # Prometheus metrics
│   ├── meta_learning/
│   │   ├── performance_tracker.py     # Mission outcome tracking
│   │   └── adaptive_engine.py         # Learning & optimization
│   └── config/settings.py             # Updated with OTEL config
├── cli/
│   ├── omnipath.py                    # CLI application
│   ├── requirements.txt
│   └── README.md
├── grafana/
│   ├── dashboards/
│   │   ├── system_overview.json
│   │   ├── agent_economy.json
│   │   └── llm_performance.json
│   ├── provisioning/
│   │   ├── datasources.yml
│   │   └── dashboards.yml
│   └── README.md
└── docker-compose.v3.yml              # Updated with all services
```

---

## 🚀 Quick Start

### 1. Pull the Latest Code

```bash
cd /home/inmoa/projects/omnipath_v2
git checkout v5.0-rewrite
git pull origin v5.0-rewrite
```

### 2. Start All Services

```bash
docker-compose -f docker-compose.v3.yml down
docker-compose -f docker-compose.v3.yml build --no-cache
docker-compose -f docker-compose.v3.yml up -d
```

### 3. Verify Everything is Running

```bash
# Check all containers
docker-compose -f docker-compose.v3.yml ps

# Test backend
curl http://localhost:8000/health

# Check metrics
curl http://localhost:8000/metrics
```

### 4. Access the Interfaces

- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **Jaeger**: http://localhost:16686
- **NATS Monitor**: http://localhost:8222

### 5. Install and Use CLI

```bash
cd cli
pip install -r requirements.txt
./omnipath.py status
./omnipath.py --help
```

---

## 📖 Feature Guide

### Observability

**Metrics Available:**

All metrics are exposed at `/metrics` and scraped by Prometheus:

```
# Mission Metrics
omnipath_missions_total{complexity, status}
omnipath_mission_duration_seconds
omnipath_active_missions

# Agent Metrics
omnipath_agent_invocations_total{model}
omnipath_agent_errors_total{model}

# Economy Metrics
omnipath_credits_earned_total{agent_id}
omnipath_credits_spent_total{agent_id}
omnipath_agent_balance{agent_id}

# LLM Metrics
omnipath_llm_api_calls_total{model}
omnipath_llm_tokens_used_total{model}
omnipath_llm_cost_total{model}
omnipath_llm_latency_seconds{model}

# HTTP Metrics
omnipath_http_requests_total{method, endpoint, status}
omnipath_http_request_duration_seconds
```

**Tracing:**

All requests are traced with OpenTelemetry. View traces in Jaeger:

1. Open http://localhost:16686
2. Select "omnipath" service
3. Click "Find Traces"
4. View detailed span information

### Meta-Learning

**API Endpoints:**

```bash
# Get agent performance
GET /api/v1/meta-learning/performance/{agent_id}

# View leaderboard
GET /api/v1/meta-learning/leaderboard?metric=success_rate&limit=10

# Get learning insights
GET /api/v1/meta-learning/insights/{agent_id}

# Get full analysis
GET /api/v1/meta-learning/analysis/{agent_id}

# Get recommendations
GET /api/v1/meta-learning/recommendations/{agent_id}

# Auto-optimize agent
POST /api/v1/meta-learning/optimize/{agent_id}

# System-wide insights
GET /api/v1/meta-learning/system-insights

# Record mission outcome
POST /api/v1/meta-learning/record-outcome
```

**How It Works:**

1. Every mission outcome is recorded
2. System tracks: duration, cost, quality, model, complexity
3. Analyzes patterns across missions
4. Identifies optimal configurations
5. Generates recommendations
6. Can auto-tune agent settings

**Example Usage:**

```bash
# Get insights for an agent
curl http://localhost:8000/api/v1/meta-learning/insights/agent_123

# Auto-optimize
curl -X POST http://localhost:8000/api/v1/meta-learning/optimize/agent_123
```

### CLI

**Installation:**

```bash
cd cli
pip install -r requirements.txt
chmod +x omnipath.py
```

**Commands:**

```bash
# System
omnipath status                          # Check system health
omnipath config                          # Configure API endpoint

# Agents
omnipath agent list                      # List all agents
omnipath agent list --status active      # Filter by status
omnipath agent show <id>                 # Show agent details
omnipath agent performance <id>          # Performance metrics

# Missions
omnipath mission list                    # List missions
omnipath mission list --status success   # Filter by status

# Economy
omnipath economy balance --agent <id>    # Check credits
omnipath economy transactions            # View transactions

# Learning
omnipath learning leaderboard            # Top performers
omnipath learning leaderboard --metric cost  # Rank by cost
omnipath learning insights <id>          # AI insights
omnipath learning optimize <id>          # Auto-tune agent
```

**Features:**

- Beautiful colored output
- Rich tables with borders
- Progress indicators
- Smart defaults
- Comprehensive help

### Grafana Dashboards

**Access:**

1. Open http://localhost:3000
2. Login: admin/admin
3. Go to Dashboards
4. Select a dashboard

**Available Dashboards:**

1. **System Overview**
   - Mission metrics
   - Success rates
   - Performance
   - Error tracking

2. **Agent Economy**
   - Credits earned/spent
   - Agent balances
   - Top earners/spenders
   - Economy health

3. **LLM Performance**
   - API calls
   - Token usage
   - Costs by model
   - Latency tracking

**Customization:**

- Click any panel to edit
- Add new panels
- Create alerts
- Export/import dashboards

---

## 🧪 Testing v5.0

### 1. Test Observability

```bash
# Generate some traffic
for i in {1..10}; do
  curl http://localhost:8000/health
done

# Check metrics are being recorded
curl http://localhost:8000/metrics | grep omnipath

# View in Prometheus
# Open http://localhost:9090
# Query: omnipath_http_requests_total

# View traces in Jaeger
# Open http://localhost:16686
# Select "omnipath" service
```

### 2. Test Meta-Learning

```bash
# Check the API is available
curl http://localhost:8000/api/v1/meta-learning/system-insights

# View leaderboard
curl http://localhost:8000/api/v1/meta-learning/leaderboard

# Get insights for an agent (replace with real agent_id)
curl http://localhost:8000/api/v1/meta-learning/insights/test_agent
```

### 3. Test CLI

```bash
cd cli

# Test status
./omnipath.py status

# Test help
./omnipath.py --help
./omnipath.py agent --help

# Test commands (will show empty data if no agents/missions yet)
./omnipath.py agent list
./omnipath.py learning leaderboard
```

### 4. Test Grafana

1. Open http://localhost:3000
2. Login: admin/admin
3. Go to Dashboards
4. Open "Omnipath System Overview"
5. Verify panels are loading (may show "No data" if no activity yet)
6. Generate some traffic and refresh

---

## 🔧 Configuration

### Environment Variables

Set in `docker-compose.v3.yml` or `.env`:

```bash
# Database
DATABASE_URL=postgresql://omnipath:omnipath@postgres:5432/omnipath

# Redis
REDIS_URL=redis://redis:6379/0

# NATS
NATS_URL=nats://nats:4222

# OpenTelemetry
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
OTEL_SERVICE_NAME=omnipath

# Application
DEBUG=True
ENVIRONMENT=development
```

### CLI Configuration

```bash
# Configure API endpoint
./omnipath.py config

# Or manually edit ~/.omnipath/config.json
{
  "api_url": "http://localhost:8000"
}
```

---

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         User Layer                          │
├─────────────┬─────────────────┬─────────────────────────────┤
│     CLI     │   Grafana UI    │      API Clients           │
└─────────────┴─────────────────┴─────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                    Omnipath Backend                         │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │   FastAPI  │  │ Meta-Learning│  │  Observability   │   │
│  │    API     │  │    System    │  │  (OpenTelemetry) │   │
│  └────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌──────────────┐  ┌────────────┐  ┌────────────┐
│  PostgreSQL  │  │   Redis    │  │    NATS    │
│  (Database)  │  │  (Cache)   │  │ (Events)   │
└──────────────┘  └────────────┘  └────────────┘
                         │
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
┌──────────────┐  ┌────────────┐  ┌────────────┐
│  Prometheus  │  │   Jaeger   │  │  Grafana   │
│  (Metrics)   │  │  (Traces)  │  │ (Dashboards)│
└──────────────┘  └────────────┘  └────────────┘
```

---

## 🎓 Learning Resources

### For Developers

- **API Documentation**: http://localhost:8000/docs
- **Prometheus Queries**: http://localhost:9090/graph
- **Jaeger Traces**: http://localhost:16686
- **Grafana Dashboards**: http://localhost:3000

### Key Files to Read

1. `backend/integrations/observability/telemetry.py` - Observability implementation
2. `backend/meta_learning/performance_tracker.py` - Performance tracking
3. `backend/meta_learning/adaptive_engine.py` - Learning algorithms
4. `cli/omnipath.py` - CLI implementation
5. `grafana/README.md` - Dashboard customization guide

---

## 🐛 Troubleshooting

### Backend Won't Start

```bash
# Check logs
docker logs omnipath-backend

# Common issues:
# 1. Database not ready - wait for postgres health check
# 2. Port 8000 in use - change port in docker-compose
# 3. Missing environment variables - check .env file
```

### No Metrics in Grafana

```bash
# 1. Check Prometheus is scraping
curl http://localhost:9090/api/v1/targets

# 2. Check backend metrics endpoint
curl http://localhost:8000/metrics

# 3. Check Grafana datasource
# Open http://localhost:3000/datasources
# Test connection to Prometheus
```

### CLI Not Connecting

```bash
# 1. Check backend is running
curl http://localhost:8000/health

# 2. Configure CLI
./omnipath.py config

# 3. Check config file
cat ~/.omnipath/config.json
```

### No Traces in Jaeger

```bash
# 1. Check Jaeger is running
curl http://localhost:16686

# 2. Check OTEL endpoint in backend
docker logs omnipath-backend | grep -i otel

# 3. Generate some traffic
curl http://localhost:8000/health
```

---

## 🚀 What's Next

### Immediate Next Steps

1. **Create Some Agents** - Use the API to create test agents
2. **Run Missions** - Execute missions to generate data
3. **Watch the Dashboards** - See metrics flow in real-time
4. **Try Meta-Learning** - Get insights and optimize agents
5. **Use the CLI** - Manage everything from terminal

### Future Enhancements

- Web UI for visual agent management
- Advanced alerting rules
- Custom dashboard templates
- Agent collaboration features
- Marketplace integration
- Advanced learning algorithms

---

## 📝 Changelog

### v5.0.0 (2026-02-01)

**Added:**
- Real OpenTelemetry distributed tracing
- Prometheus metrics for all operations
- Meta-learning system with performance tracking
- Adaptive engine for agent optimization
- 15 new meta-learning API endpoints
- CLI interface with beautiful terminal UI
- 3 Grafana dashboards with auto-provisioning
- Comprehensive documentation

**Changed:**
- Rebuilt from v4.5 baseline with proper architecture
- Updated settings with observability configuration
- Enhanced main.py with telemetry initialization
- Version bumped to 5.0.0

**Fixed:**
- Meter/tracer None handling in mission_executor
- Proper graceful degradation when observability unavailable

---

## 👥 Credits

**Built by:** Omnipath Development Team (Manus AI)  
**For:** Obex Blackvault  
**With:** Pride (proper actions, every time)

---

## 📄 License

Proprietary - Omnipath v2 Project

---

**Welcome to Omnipath v5.0! 🎉**

*Built properly. Built with pride.*
