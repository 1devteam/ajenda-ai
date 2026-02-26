# OMNIPATH V2 - QUICKSTART GUIDE

**Production-Ready Multi-Agent Platform with Full Observability**

Built with Pride for Obex Blackvault by the Dev Team

---

## 🚀 WHAT YOU HAVE

✅ **80 Tests** - Comprehensive test coverage  
✅ **OpenTelemetry** - Full observability stack installed  
✅ **Specialized Agents** - ResearcherAgent, AnalystAgent, DeveloperAgent  
✅ **Jaeger Tracing** - Already working (as shown in your screenshot)  
✅ **Prometheus Metrics** - Already working (backend:8000 UP)  
✅ **API Endpoints** - 7 new agent endpoints ready to use  
✅ **Environment Configured** - OpenAI, Anthropic, Google, Langfuse  

---

## 📍 YOUR SETUP

**Repository Location:** `/home/inmoa/projects/omnipath_v2` (on your machine)  
**Virtual Environment:** `venv_clean` (on your machine)  
**Database:** SQLite (development mode)  
**Observability:** Jaeger (http://localhost:16686), Prometheus (http://localhost:9090)  

---

## 🎯 METHOD 1: START THE SERVER (RECOMMENDED)

### Step 1: Kill Any Existing Processes

```bash
# Kill processes on ports 8000 and 8001 (if running)
sudo lsof -ti:8000 | xargs kill -9 2>/dev/null || true
sudo lsof -ti:8001 | xargs kill -9 2>/dev/null || true

# OR use the helper script
./kill_ports.sh
```

### Step 2: Activate Virtual Environment

```bash
cd ~/p/omnipath_v2
source venv_clean/bin/activate
```

### Step 3: Start the FastAPI Server

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# OR use the helper script
./start_server.sh
```

**Expected Output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [12345] using StatReload
INFO:     Started server process [12346]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

### Step 4: Open API Documentation

**Swagger UI:** http://localhost:8000/docs  
**ReDoc:** http://localhost:8000/redoc  

---

## 🔐 METHOD 2: REGISTER & AUTHENTICATE

### Step 1: Register a New User

**Open a NEW terminal** (keep server running in first terminal):

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "your@email.com",
    "password": "YourSecurePassword123!",
    "tenant_name": "My Company"
  }'
```

**Expected Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "user_abc123",
    "email": "your@email.com",
    "tenant_id": "tenant_xyz789"
  }
}
```

**⚠️ SAVE YOUR ACCESS TOKEN!** You'll need it for all subsequent requests.

### Step 2: Set Your Token as Environment Variable

```bash
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

(Replace with your actual token from Step 1)

---

## 🤖 METHOD 3: USE SPECIALIZED AGENTS

### ResearcherAgent - Deep Research Tasks

**Use Case:** "Research the latest developments in quantum computing"

```bash
curl -X POST http://localhost:8000/api/v1/agents/research \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "What are the latest breakthroughs in quantum computing in 2026?",
    "depth": "deep",
    "max_iterations": 3
  }'
```

**Parameters:**
- `query` (required): Research question
- `depth` (optional): "quick", "standard", or "deep" (default: "standard")
- `max_iterations` (optional): Number of research cycles (default: 3)

**Response:**
```json
{
  "agent_type": "researcher",
  "result": {
    "findings": "...",
    "sources": [...],
    "confidence": 0.92
  },
  "metadata": {
    "iterations": 3,
    "tools_used": ["web_search", "file_reader"],
    "duration_seconds": 12.5
  }
}
```

### AnalystAgent - Data Analysis Tasks

**Use Case:** "Analyze sales data and identify trends"

```bash
curl -X POST http://localhost:8000/api/v1/agents/analyze \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "data": {
      "sales": [100, 150, 200, 180, 220],
      "months": ["Jan", "Feb", "Mar", "Apr", "May"]
    },
    "analysis_type": "trend"
  }'
```

**Parameters:**
- `data` (required): Data to analyze (dict, list, or JSON)
- `analysis_type` (optional): "descriptive", "trend", "correlation", "predictive" (default: "descriptive")

**Response:**
```json
{
  "agent_type": "analyst",
  "result": {
    "analysis": "...",
    "insights": [...],
    "visualizations": [...]
  },
  "metadata": {
    "analysis_type": "trend",
    "data_points": 5,
    "duration_seconds": 3.2
  }
}
```

### DeveloperAgent - Code Generation Tasks

**Use Case:** "Generate a Python function to calculate Fibonacci numbers"

```bash
curl -X POST http://localhost:8000/api/v1/agents/develop \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "task": "Create a Python function to calculate the nth Fibonacci number using dynamic programming",
    "language": "python",
    "include_tests": true
  }'
```

**Parameters:**
- `task` (required): Development task description
- `language` (optional): Programming language (default: "python")
- `include_tests` (optional): Generate unit tests (default: true)

**Response:**
```json
{
  "agent_type": "developer",
  "result": {
    "code": "def fibonacci(n: int) -> int:\n    ...",
    "tests": "def test_fibonacci():\n    ...",
    "documentation": "..."
  },
  "metadata": {
    "language": "python",
    "lines_of_code": 25,
    "duration_seconds": 5.8
  }
}
```

---

## 🔧 METHOD 4: GENERIC AGENT EXECUTION

**Use Case:** Let the system automatically choose the best agent for your task

```bash
curl -X POST http://localhost:8000/api/v1/agents/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "task": "Research the impact of AI on healthcare and analyze the data",
    "context": {
      "priority": "high",
      "deadline": "2026-03-01"
    }
  }'
```

**How It Works:**
- **AgentFactory** analyzes your task keywords
- Automatically selects: ResearcherAgent, AnalystAgent, or DeveloperAgent
- Keywords: "research" → Researcher, "analyze" → Analyst, "code/develop" → Developer

---

## 📊 METHOD 5: VIEW AVAILABLE TOOLS & AGENTS

### List All Agent Types

```bash
curl -X GET http://localhost:8000/api/v1/agents/types \
  -H "Authorization: Bearer $TOKEN"
```

### List Available Tools

```bash
curl -X GET http://localhost:8000/api/v1/agents/tools \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🐍 METHOD 6: PYTHON PROGRAMMATIC USAGE

### Example 1: Use AgentFactory Directly

```python
import asyncio
from backend.agents.factory.agent_factory import AgentFactory

async def main():
    factory = AgentFactory()
    
    # Create a researcher agent
    agent = factory.create_agent(
        agent_type="researcher",
        config={
            "model": "gpt-4.1-mini",
            "temperature": 0.7
        }
    )
    
    # Execute research task
    result = await agent.execute({
        "query": "What is LangGraph?",
        "depth": "standard"
    })
    
    print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Example 2: Use MissionExecutor with Specialized Agents

```python
import asyncio
from backend.orchestration.mission_executor import MissionExecutor
from backend.models.domain.mission import Mission, MissionStatus

async def main():
    executor = MissionExecutor()
    
    # Create a mission
    mission = Mission(
        id="mission_001",
        title="Research and Analyze AI Trends",
        description="Research latest AI trends and analyze the data",
        status=MissionStatus.PENDING,
        assigned_agents=["researcher", "analyst"],
        tenant_id="test_tenant"
    )
    
    # Execute mission (will use specialized agents automatically)
    result = await executor.execute_mission(mission)
    
    print(f"Mission Status: {result.status}")
    print(f"Result: {result.result}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 📈 METHOD 7: VIEW OBSERVABILITY DASHBOARDS

### Jaeger Tracing

**URL:** http://localhost:16686

**What You'll See:**
- Trace timelines for `execute_mission` operations
- Service dependencies
- Performance bottlenecks
- Error traces

### Prometheus Metrics

**URL:** http://localhost:9090

**What You'll See:**
- Target status: `omnipath-backend` (UP)
- Scrape duration
- Health monitoring

### Langfuse (Configured)

**Your .env has:**
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST`

All LLM calls are automatically traced.

---

## 🧪 METHOD 8: RUN TESTS LOCALLY

### Run Specific Test Files

```bash
cd ~/p/omnipath_v2
source venv_clean/bin/activate

# Run economy tests
python3.11 -m pytest tests/unit/test_economy.py -v

# Run specialized agent tests
python3.11 -m pytest tests/integration/test_specialized_agents.py -v
```

### Run All Unit Tests

```bash
python3.11 -m pytest tests/unit/ -v --tb=short
```

### Run With Coverage

```bash
python3.11 -m pytest tests/ --cov=backend --cov-report=html
```

---

## 🛠️ TROUBLESHOOTING

### Problem: Port 8000 Already in Use

**Solution:**
```bash
sudo lsof -ti:8000 | xargs kill -9
# OR
./kill_ports.sh
```

### Problem: "ModuleNotFoundError"

**Solution:**
```bash
cd ~/p/omnipath_v2
source venv_clean/bin/activate
pip install -r requirements.txt
```

### Problem: "OpenTelemetry tracer not available"

**Solution:**
```bash
sudo pip3 install opentelemetry-api opentelemetry-sdk \
  opentelemetry-instrumentation-fastapi \
  opentelemetry-exporter-jaeger \
  opentelemetry-exporter-prometheus
```

### Problem: Authentication Fails

**Solution:**
```bash
# Check .env file has JWT secret
cat .env | grep JWT_SECRET_KEY

# If missing, add:
echo 'JWT_SECRET_KEY="your-secret-key-here"' >> .env

# Restart server
```

---

## 📚 QUICK REFERENCE

### All API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/auth/register` | POST | Register new user |
| `/api/v1/auth/login` | POST | Login user |
| `/api/v1/agents/types` | GET | List agent types |
| `/api/v1/agents/execute` | POST | Execute generic agent |
| `/api/v1/agents/research` | POST | Execute researcher |
| `/api/v1/agents/analyze` | POST | Execute analyst |
| `/api/v1/agents/develop` | POST | Execute developer |
| `/api/v1/agents/tools` | GET | List available tools |
| `/api/v1/economy/balance` | GET | Get agent balances |
| `/api/v1/missions` | GET | List missions |
| `/api/v1/missions` | POST | Create mission |
| `/metrics` | GET | Prometheus metrics |

### Environment Variables

```bash
# Required
SECRET_KEY="your-secret-key"
JWT_SECRET_KEY="your-jwt-secret"
OPENAI_API_KEY="sk-..."

# Optional
ANTHROPIC_API_KEY="sk-ant-..."
GOOGLE_API_KEY="..."
LANGFUSE_PUBLIC_KEY="pk-..."
LANGFUSE_SECRET_KEY="sk-..."
LANGFUSE_HOST="https://cloud.langfuse.com"
```

---

## 🎓 UNDERSTANDING AGENT TYPES

### When to Use ResearcherAgent

**Best For:**
- Web research tasks
- Information gathering
- Fact-checking
- Literature reviews
- Competitive analysis

**Example Tasks:**
- "Research the top 10 AI companies in 2026"
- "Find the latest papers on transformer models"
- "What are the best practices for API design?"

### When to Use AnalystAgent

**Best For:**
- Data analysis
- Statistical analysis
- Trend identification
- Pattern recognition
- Data visualization

**Example Tasks:**
- "Analyze this sales data and identify trends"
- "Calculate correlation between marketing spend and revenue"
- "Create a visualization of user growth over time"

### When to Use DeveloperAgent

**Best For:**
- Code generation
- Bug fixing
- Code review
- Test generation
- Documentation

**Example Tasks:**
- "Generate a REST API for user management"
- "Write unit tests for this function"
- "Refactor this code to improve performance"

---

## 🚦 QUICK START (3 STEPS)

### 1. Start the Server
```bash
cd ~/p/omnipath_v2
source venv_clean/bin/activate
./start_server.sh
```

### 2. Register a User (New Terminal)
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "test@example.com", "password": "test123", "tenant_name": "Test"}'
```

### 3. Try Your First Agent
```bash
export TOKEN="<your-access-token>"

curl -X POST http://localhost:8000/api/v1/agents/research \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "What is LangGraph?", "depth": "standard"}'
```

---

**Built with Pride by the Dev Team for Obex Blackvault**

*Quality > Speed | Production-Grade Code Only | Every Line Represents You*
