#!/bin/bash
# Example API Commands for Omnipath V2
# Copy and paste these commands to test the API

# ============================================================================
# STEP 1: REGISTER A USER
# ============================================================================

echo "📝 Registering a new user..."
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "TestPassword123!",
    "tenant_name": "My Company"
  }'

echo -e "\n\n⚠️  IMPORTANT: Copy the access_token from the response above!"
echo "Then run: export TOKEN=\"your-access-token-here\""
echo ""

# ============================================================================
# STEP 2: SET YOUR TOKEN (MANUAL STEP)
# ============================================================================

# After registering, copy your token and run:
# export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# ============================================================================
# STEP 3: TEST RESEARCHER AGENT
# ============================================================================

echo "🔬 Testing ResearcherAgent..."
curl -X POST http://localhost:8000/api/v1/agents/research \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "What is LangGraph and how does it work?",
    "depth": "standard",
    "max_iterations": 3
  }'

echo -e "\n\n"

# ============================================================================
# STEP 4: TEST ANALYST AGENT
# ============================================================================

echo "📊 Testing AnalystAgent..."
curl -X POST http://localhost:8000/api/v1/agents/analyze \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "data": {
      "sales": [100, 150, 200, 180, 220, 250],
      "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
    },
    "analysis_type": "trend"
  }'

echo -e "\n\n"

# ============================================================================
# STEP 5: TEST DEVELOPER AGENT
# ============================================================================

echo "💻 Testing DeveloperAgent..."
curl -X POST http://localhost:8000/api/v1/agents/develop \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "task": "Create a Python function to calculate factorial using recursion",
    "language": "python",
    "include_tests": true
  }'

echo -e "\n\n"

# ============================================================================
# STEP 6: LIST AGENT TYPES
# ============================================================================

echo "📋 Listing available agent types..."
curl -X GET http://localhost:8000/api/v1/agents/types \
  -H "Authorization: Bearer $TOKEN"

echo -e "\n\n"

# ============================================================================
# STEP 7: LIST AVAILABLE TOOLS
# ============================================================================

echo "🛠️  Listing available tools..."
curl -X GET http://localhost:8000/api/v1/agents/tools \
  -H "Authorization: Bearer $TOKEN"

echo -e "\n\n"

# ============================================================================
# STEP 8: GENERIC AGENT EXECUTION
# ============================================================================

echo "🤖 Testing generic agent execution (auto-selects agent)..."
curl -X POST http://localhost:8000/api/v1/agents/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "task": "Research the benefits of microservices architecture",
    "context": {
      "priority": "high"
    }
  }'

echo -e "\n\n"

# ============================================================================
# STEP 9: CHECK ECONOMY BALANCE
# ============================================================================

echo "💰 Checking agent balances..."
curl -X GET http://localhost:8000/api/v1/economy/balance \
  -H "Authorization: Bearer $TOKEN"

echo -e "\n\n"

# ============================================================================
# STEP 10: HEALTH CHECK
# ============================================================================

echo "❤️  Checking server health..."
curl -X GET http://localhost:8000/health

echo -e "\n\n✅ All commands executed!"
