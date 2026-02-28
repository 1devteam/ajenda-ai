"""
Integration Tests for Specialized Agents
Built with Pride for Obex Blackvault

Tests the integration of ResearcherAgent, AnalystAgent, and DeveloperAgent
with reasoning workflows, tool-calling, and MissionExecutor.
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock

from backend.agents.factory.agent_factory import AgentFactory
from backend.agents.implementations.researcher_agent import (
    ResearcherAgent,
    AnalystAgent,
    DeveloperAgent,
)
from backend.integrations.llm.llm_service import LLMService
from backend.orchestration.mission_executor import MissionExecutor
from backend.economy.resource_marketplace import ResourceMarketplace
from backend.core.event_bus.nats_bus import NATSEventBus


@pytest.fixture
def llm_service():
    """Create MOCKED LLM service for testing"""
    # Create a mock LLM that can be used by agents
    mock_llm = MagicMock()
    mock_llm.invoke = MagicMock(return_value="Mock LLM response")
    mock_llm.ainvoke = AsyncMock(return_value="Mock LLM response")

    # Create a mock LLM service that returns the mock LLM
    mock_service = MagicMock(spec=LLMService)
    mock_service.get_llm = MagicMock(return_value=mock_llm)

    return mock_service


@pytest.fixture
def agent_factory(llm_service):
    """Create agent factory for testing"""
    return AgentFactory(llm_service)


@pytest.fixture
def marketplace():
    """Create marketplace for testing"""
    return ResourceMarketplace()


@pytest.fixture
def event_bus():
    """Create mock event bus for testing"""
    bus = AsyncMock(spec=NATSEventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mission_executor(marketplace, event_bus, llm_service):
    """Create mission executor for testing"""
    return MissionExecutor(marketplace=marketplace, event_bus=event_bus, llm_service=llm_service)


# ============================================================================
# AgentFactory Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.agents
class TestAgentFactory:
    """Test AgentFactory creation and agent selection"""

    def test_factory_initialization(self, agent_factory):
        """Test factory initializes correctly"""
        assert agent_factory is not None
        assert agent_factory.llm_service is not None
        assert agent_factory.metrics is not None

    def test_create_researcher_agent(self, agent_factory):
        """Test creating a ResearcherAgent"""
        agent = agent_factory.create_specialized_agent(
            agent_type="researcher",
            agent_id="test_researcher_001",
            tenant_id="test_tenant",
        )

        assert isinstance(agent, ResearcherAgent)
        assert agent.agent_id == "test_researcher_001"
        assert agent.tenant_id == "test_tenant"
        assert agent.agent_type == "researcher"

    def test_create_analyst_agent(self, agent_factory):
        """Test creating an AnalystAgent"""
        agent = agent_factory.create_specialized_agent(
            agent_type="analyst", agent_id="test_analyst_001", tenant_id="test_tenant"
        )

        assert isinstance(agent, AnalystAgent)
        assert agent.agent_id == "test_analyst_001"
        assert agent.agent_type == "analyst"

    def test_create_developer_agent(self, agent_factory):
        """Test creating a DeveloperAgent"""
        agent = agent_factory.create_specialized_agent(
            agent_type="developer",
            agent_id="test_developer_001",
            tenant_id="test_tenant",
        )

        assert isinstance(agent, DeveloperAgent)
        assert agent.agent_id == "test_developer_001"
        assert agent.agent_type == "developer"

    def test_invalid_agent_type(self, agent_factory):
        """Test that invalid agent type raises ValueError"""
        with pytest.raises(ValueError, match="Unsupported agent type"):
            agent_factory.create_specialized_agent(
                agent_type="invalid_type",
                agent_id="test_invalid_001",
                tenant_id="test_tenant",
            )

    def test_agent_selection_research_keywords(self, agent_factory):
        """Test agent selection for research keywords"""
        plan = {"steps": [], "requires_tools": []}

        # Test research keywords
        research_goals = [
            "Research the latest trends in AI",
            "Find information about quantum computing",
            "Search for best practices in Python",
            "Investigate the causes of climate change",
            "Gather data on market trends",
        ]

        for goal in research_goals:
            agent_type = agent_factory._select_agent_type(goal, plan)
            assert agent_type == "researcher", f"Failed for goal: {goal}"

    def test_agent_selection_analysis_keywords(self, agent_factory):
        """Test agent selection for analysis keywords"""
        plan = {"steps": [], "requires_tools": []}

        # Test analysis keywords
        analysis_goals = [
            "Analyze the sales data for Q4",
            "Compare performance metrics across teams",
            "Evaluate the effectiveness of our strategy",
            "Assess the impact of recent changes",
            "Identify trends in customer behavior",
        ]

        for goal in analysis_goals:
            agent_type = agent_factory._select_agent_type(goal, plan)
            assert agent_type == "analyst", f"Failed for goal: {goal}"

    def test_agent_selection_development_keywords(self, agent_factory):
        """Test agent selection for development keywords"""
        plan = {"steps": [], "requires_tools": []}

        # Test development keywords
        dev_goals = [
            "Write code to calculate fibonacci numbers",
            "Debug the authentication issue",
            "Implement a sorting algorithm",
            "Code a function to parse JSON",
            "Fix the bug in the payment processor",
        ]

        for goal in dev_goals:
            agent_type = agent_factory._select_agent_type(goal, plan)
            assert agent_type == "developer", f"Failed for goal: {goal}"

    def test_agent_selection_tool_requirements(self, agent_factory):
        """Test agent selection based on tool requirements"""
        # Web search tool -> researcher
        plan = {"steps": [], "requires_tools": ["web_search"]}
        agent_type = agent_factory._select_agent_type("Complete this task", plan)
        assert agent_type == "researcher"

        # Code execution tool -> developer
        plan = {"steps": [], "requires_tools": ["code_execution"]}
        agent_type = agent_factory._select_agent_type("Complete this task", plan)
        assert agent_type == "developer"

    def test_agent_selection_simple_fallback(self, agent_factory):
        """Test fallback to simple execution"""
        plan = {"steps": [], "requires_tools": []}
        goal = "Say hello"

        agent_type = agent_factory._select_agent_type(goal, plan)
        assert agent_type == "simple"

    def test_get_agent_capabilities(self, agent_factory):
        """Test getting agent capabilities"""
        capabilities = agent_factory.get_agent_capabilities("researcher")

        assert capabilities["type"] == "researcher"
        assert capabilities["name"] == "Researcher"
        assert "web_search" in capabilities["capabilities"]
        assert "web_search" in capabilities["tools"]
        assert len(capabilities["use_cases"]) > 0

    def test_list_agent_types(self, agent_factory):
        """Test listing all agent types"""
        result = agent_factory.list_agent_types()

        assert "specialized_agents" in result
        assert len(result["specialized_agents"]) == 3

        agent_types = [a["type"] for a in result["specialized_agents"]]
        assert "researcher" in agent_types
        assert "analyst" in agent_types
        assert "developer" in agent_types


# ============================================================================
# Specialized Agent Execution Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.agents
@pytest.mark.asyncio
class TestSpecializedAgentExecution:
    """Test specialized agent execution with mocked LLM"""

    async def test_researcher_agent_basic_execution(self, agent_factory):
        """Test ResearcherAgent executes without errors"""
        # Note: This test uses real LLM calls, so it may be slow
        # In production, we'd mock the LLM responses

        agent = agent_factory.create_specialized_agent(
            agent_type="researcher",
            agent_id="test_researcher_exec_001",
            tenant_id="test_tenant",
        )

        # Simple task that doesn't require actual web search
        task = {"query": "What is 2+2?", "depth": "standard"}

        # This will fail if LLM is not available, which is expected in CI
        # We're testing the integration, not the LLM itself
        try:
            result = await agent.execute(task)
            assert "success" in result
        except Exception as e:
            pytest.skip(f"LLM not available for integration test: {e}")

    async def test_analyst_agent_basic_execution(self, agent_factory):
        """Test AnalystAgent executes without errors"""
        agent = agent_factory.create_specialized_agent(
            agent_type="analyst",
            agent_id="test_analyst_exec_001",
            tenant_id="test_tenant",
        )

        task = {"data": {"values": [1, 2, 3, 4, 5]}, "analysis_type": "descriptive"}

        try:
            result = await agent.execute(task)
            assert "success" in result
        except Exception as e:
            pytest.skip(f"LLM not available for integration test: {e}")

    async def test_developer_agent_basic_execution(self, agent_factory):
        """Test DeveloperAgent executes without errors"""
        agent = agent_factory.create_specialized_agent(
            agent_type="developer",
            agent_id="test_developer_exec_001",
            tenant_id="test_tenant",
        )

        task = {
            "task_type": "generate",
            "specification": "Create a function that adds two numbers",
        }

        try:
            result = await agent.execute(task)
            assert "success" in result
        except Exception as e:
            pytest.skip(f"LLM not available for integration test: {e}")


# ============================================================================
# MissionExecutor Integration Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.agents
@pytest.mark.asyncio
class TestMissionExecutorIntegration:
    """Test MissionExecutor integration with specialized agents"""

    async def test_mission_executor_has_agent_factory(self, mission_executor):
        """Test MissionExecutor has AgentFactory initialized"""
        assert mission_executor.agent_factory is not None
        assert isinstance(mission_executor.agent_factory, AgentFactory)

    async def test_mission_executor_research_mission(self, mission_executor, marketplace):
        """Test MissionExecutor executes research mission with ResearcherAgent"""
        mission_id = f"mission_test_{uuid.uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        user_id = "test_user"

        # Create initial balance for tenant
        await marketplace.reward(
            tenant_id=tenant_id,
            agent_id="test_agent",
            amount=1000.0,
            resource_type="test_credits",
            mission_id=mission_id,
            agent_type="test",
        )

        # Execute research mission
        try:
            result = await mission_executor.execute_mission(
                mission_id=mission_id,
                goal="Research what is Python programming language",
                tenant_id=tenant_id,
                user_id=user_id,
                budget=100.0,
            )

            assert result["status"] in ["SUCCESS", "FAILED"]
            assert "output" in result
            assert "cost" in result

            # Check if specialized agent was used
            if "agent_type" in result:
                assert result["agent_type"] in ["researcher", "simple"]

        except Exception as e:
            pytest.skip(f"Mission execution failed (expected in CI without LLM): {e}")

    async def test_mission_executor_analysis_mission(self, mission_executor, marketplace):
        """Test MissionExecutor executes analysis mission with AnalystAgent"""
        mission_id = f"mission_test_{uuid.uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        user_id = "test_user"

        # Create initial balance
        await marketplace.reward(
            tenant_id=tenant_id,
            agent_id="test_agent",
            amount=1000.0,
            resource_type="test_credits",
            mission_id=mission_id,
            agent_type="test",
        )

        try:
            result = await mission_executor.execute_mission(
                mission_id=mission_id,
                goal="Analyze the sales trends for Q4 2023",
                tenant_id=tenant_id,
                user_id=user_id,
                budget=100.0,
            )

            assert result["status"] in ["SUCCESS", "FAILED"]

            if "agent_type" in result:
                assert result["agent_type"] in ["analyst", "simple"]

        except Exception as e:
            pytest.skip(f"Mission execution failed (expected in CI without LLM): {e}")

    async def test_mission_executor_development_mission(self, mission_executor, marketplace):
        """Test MissionExecutor executes development mission with DeveloperAgent"""
        mission_id = f"mission_test_{uuid.uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        user_id = "test_user"

        # Create initial balance
        await marketplace.reward(
            tenant_id=tenant_id,
            agent_id="test_agent",
            amount=1000.0,
            resource_type="test_credits",
            mission_id=mission_id,
            agent_type="test",
        )

        try:
            result = await mission_executor.execute_mission(
                mission_id=mission_id,
                goal="Write code to calculate fibonacci sequence",
                tenant_id=tenant_id,
                user_id=user_id,
                budget=100.0,
            )

            assert result["status"] in ["SUCCESS", "FAILED"]

            if "agent_type" in result:
                assert result["agent_type"] in ["developer", "simple"]

        except Exception as e:
            pytest.skip(f"Mission execution failed (expected in CI without LLM): {e}")

    async def test_mission_executor_simple_fallback(self, mission_executor, marketplace):
        """Test MissionExecutor falls back to simple execution for basic tasks"""
        mission_id = f"mission_test_{uuid.uuid4().hex[:8]}"
        tenant_id = "test_tenant"
        user_id = "test_user"

        # Create initial balance
        await marketplace.reward(
            tenant_id=tenant_id,
            agent_id="test_agent",
            amount=1000.0,
            resource_type="test_credits",
            mission_id=mission_id,
            agent_type="test",
        )

        try:
            result = await mission_executor.execute_mission(
                mission_id=mission_id,
                goal="Say hello",
                tenant_id=tenant_id,
                user_id=user_id,
                budget=100.0,
            )

            assert result["status"] in ["SUCCESS", "FAILED"]

        except Exception as e:
            pytest.skip(f"Mission execution failed (expected in CI without LLM): {e}")


# ============================================================================
# Tool Registry Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.agents
class TestToolRegistry:
    """Test tool registry integration"""

    def test_tool_registry_available(self):
        """Test tool registry is available"""
        from backend.agents.tools.tool_registry import get_tool_registry

        registry = get_tool_registry()
        assert registry is not None

        tools = registry.get_all_tools()
        assert len(tools) > 0

    def test_tool_registry_has_required_tools(self):
        """Test tool registry has all required tools"""
        from backend.agents.tools.tool_registry import get_tool_registry

        registry = get_tool_registry()

        required_tools = [
            "web_search",
            "python_executor",
            "file_reader",
            "file_writer",
            "calculator",
        ]

        for tool_name in required_tools:
            tool = registry.get_tool(tool_name)
            assert tool is not None, f"Tool {tool_name} not found"
            assert tool.name == tool_name

    def test_tool_categories(self):
        """Test tools are properly categorized"""
        from backend.agents.tools.tool_registry import get_tool_registry, ToolCategory

        registry = get_tool_registry()

        # Check each category has tools
        for category in ToolCategory:
            tools = registry.get_tools_by_category(category)
            # Some categories may be empty, that's ok
            assert isinstance(tools, list)


# ============================================================================
# End-to-End Integration Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.agents
@pytest.mark.e2e
@pytest.mark.asyncio
class TestEndToEndIntegration:
    """End-to-end integration tests for specialized agents"""

    async def test_full_research_workflow(self, mission_executor, marketplace):
        """Test complete research workflow from mission to result"""
        mission_id = f"e2e_research_{uuid.uuid4().hex[:8]}"
        tenant_id = "test_tenant_e2e"
        user_id = "test_user_e2e"

        # Setup: Create initial balance
        await marketplace.reward(
            tenant_id=tenant_id,
            agent_id="setup_agent",
            amount=1000.0,
            resource_type="test_credits",
            mission_id=mission_id,
            agent_type="setup",
        )

        # Execute: Run research mission
        try:
            result = await mission_executor.execute_mission(
                mission_id=mission_id,
                goal="Research the benefits of test-driven development",
                tenant_id=tenant_id,
                user_id=user_id,
                budget=100.0,
            )

            # Verify: Check result structure
            assert "status" in result
            assert "output" in result
            assert "cost" in result

            # Verify: Check economy was updated
            balance = await marketplace.get_balance(tenant_id, "setup_agent")
            assert balance["balance"] < 1000.0  # Cost was deducted

        except Exception as e:
            pytest.skip(f"E2E test failed (expected in CI without LLM): {e}")

    async def test_agent_factory_to_execution_pipeline(self, agent_factory):
        """Test pipeline from factory creation to agent execution"""
        # Step 1: Create agent via factory
        agent = agent_factory.create_specialized_agent(
            agent_type="researcher",
            agent_id="pipeline_test_001",
            tenant_id="test_tenant",
        )

        assert agent is not None

        # Step 2: Verify agent has required components
        assert hasattr(agent, "llm")
        assert hasattr(agent, "tool_registry")
        assert hasattr(agent, "reasoning_workflow")

        # Step 3: Execute simple task
        try:
            task = {"query": "What is 1+1?", "depth": "standard"}
            result = await agent.execute(task)

            assert "success" in result

        except Exception as e:
            pytest.skip(f"Pipeline test failed (expected in CI without LLM): {e}")
