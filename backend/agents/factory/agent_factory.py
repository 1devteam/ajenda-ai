"""
Agent Factory for Omnipath V2
Built with Pride for Obex Blackvault

This module provides a factory pattern for creating specialized agents
with proper LLM injection and configuration management.
"""

from typing import Dict, Any, Optional, Union
import logging
import uuid

from backend.agents.implementations.researcher_agent import (
    ResearcherAgent,
    AnalystAgent,
    DeveloperAgent
)
from backend.integrations.llm.llm_service import LLMService
from backend.integrations.observability.prometheus_metrics import get_metrics
from backend.agents.integration.governance_hooks import governance_hooks
import asyncio

logger = logging.getLogger(__name__)


class AgentFactory:
    """
    Factory for creating specialized agents with proper configuration.
    
    Responsibilities:
    - Instantiate specialized agents (Researcher, Analyst, Developer)
    - Inject appropriate LLM based on agent type
    - Manage agent lifecycle and configuration
    - Track agent creation metrics
    """
    
    def __init__(self, llm_service: LLMService):
        """
        Initialize the agent factory.
        
        Args:
            llm_service: LLM service for creating language models
        """
        self.llm_service = llm_service
        self.metrics = get_metrics()
        logger.info("AgentFactory initialized")
    
    def create_specialized_agent(
        self,
        agent_type: str,
        agent_id: str,
        tenant_id: str,
        **kwargs
    ) -> Union[ResearcherAgent, AnalystAgent, DeveloperAgent]:
        """
        Create a specialized agent instance.
        
        Args:
            agent_type: Type of agent ("researcher", "analyst", "developer")
            agent_id: Unique agent identifier
            tenant_id: Tenant ID for multi-tenancy
            **kwargs: Additional configuration for the agent
            
        Returns:
            Specialized agent instance
            
        Raises:
            ValueError: If agent_type is not supported
        """
        agent_type_lower = agent_type.lower()
        
        # Validate agent type
        if agent_type_lower not in ["researcher", "analyst", "developer"]:
            raise ValueError(
                f"Unsupported agent type: {agent_type}. "
                f"Supported types: researcher, analyst, developer"
            )
        
        # Get appropriate LLM for agent type
        try:
            llm = self.llm_service.get_llm(agent_type_lower, tenant_id)
        except Exception as e:
            logger.error(f"Failed to create LLM for {agent_type}: {e}")
            raise ValueError(f"Failed to create LLM for agent type {agent_type}: {str(e)}")
        
        # Create the specialized agent
        try:
            if agent_type_lower == "researcher":
                agent = ResearcherAgent(
                    agent_id=agent_id,
                    llm=llm,
                    tenant_id=tenant_id,
                    **kwargs
                )
                logger.info(f"Created ResearcherAgent: {agent_id}")
                
            elif agent_type_lower == "analyst":
                agent = AnalystAgent(
                    agent_id=agent_id,
                    llm=llm,
                    tenant_id=tenant_id,
                    **kwargs
                )
                logger.info(f"Created AnalystAgent: {agent_id}")
                
            elif agent_type_lower == "developer":
                agent = DeveloperAgent(
                    agent_id=agent_id,
                    llm=llm,
                    tenant_id=tenant_id,
                    **kwargs
                )
                logger.info(f"Created DeveloperAgent: {agent_id}")
            
            # Record agent creation metric
            self.metrics.record_agent_invocation(agent_type_lower, "created")
            
            # Governance hook: Register agent in governance system
            try:
                asyncio.create_task(
                    governance_hooks.on_agent_created(
                        agent_id=agent_id,
                        agent_type=agent_type_lower,
                        tenant_id=tenant_id,
                        owner_id=kwargs.get("owner_id", "system"),
                        name=kwargs.get("name", f"{agent_type_lower}_agent"),
                        model=llm.model_name if hasattr(llm, "model_name") else "unknown",
                        capabilities=kwargs.get("capabilities", []),
                        config=kwargs
                    )
                )
            except Exception as e:
                logger.warning(f"Governance hook failed (non-blocking): {e}")
            
            return agent
            
        except Exception as e:
            logger.error(f"Failed to create {agent_type} agent: {e}")
            raise ValueError(f"Failed to create agent: {str(e)}")
    
    def create_agent_for_mission(
        self,
        mission_goal: str,
        plan: Dict[str, Any],
        tenant_id: str
    ) -> Union[ResearcherAgent, AnalystAgent, DeveloperAgent, None]:
        """
        Create an appropriate specialized agent based on mission characteristics.
        
        This method analyzes the mission goal and plan to determine which
        specialized agent type is most suitable.
        
        Args:
            mission_goal: The mission objective
            plan: Execution plan with steps and requirements
            tenant_id: Tenant ID
            
        Returns:
            Specialized agent instance or None if simple execution is sufficient
        """
        agent_type = self._select_agent_type(mission_goal, plan)
        
        if agent_type == "simple":
            # No specialized agent needed
            return None
        
        # Generate unique agent ID
        agent_id = f"mission_{agent_type}_{uuid.uuid4().hex[:8]}"
        
        # Create the agent
        return self.create_specialized_agent(
            agent_type=agent_type,
            agent_id=agent_id,
            tenant_id=tenant_id
        )
    
    def _select_agent_type(self, mission_goal: str, plan: Dict[str, Any]) -> str:
        """
        Intelligently select agent type based on mission characteristics.
        
        Args:
            mission_goal: The mission objective
            plan: Execution plan with steps and requirements
            
        Returns:
            Agent type: "researcher", "analyst", "developer", or "simple"
        """
        goal_lower = mission_goal.lower()
        
        # Keywords for research tasks
        research_keywords = [
            "research", "find", "search", "investigate", "gather",
            "explore", "discover", "look up", "information about"
        ]
        
        # Keywords for analysis tasks
        analysis_keywords = [
            "analyze", "compare", "evaluate", "assess", "insights",
            "trends", "patterns", "statistics", "data", "metrics"
        ]
        
        # Keywords for development tasks
        dev_keywords = [
            "code", "program", "develop", "debug", "implement",
            "build", "function", "script", "fix", "bug"
        ]
        
        # Check mission goal for keywords
        if any(kw in goal_lower for kw in research_keywords):
            logger.info(f"Selected ResearcherAgent for mission: {mission_goal[:50]}...")
            return "researcher"
        
        elif any(kw in goal_lower for kw in analysis_keywords):
            logger.info(f"Selected AnalystAgent for mission: {mission_goal[:50]}...")
            return "analyst"
        
        elif any(kw in goal_lower for kw in dev_keywords):
            logger.info(f"Selected DeveloperAgent for mission: {mission_goal[:50]}...")
            return "developer"
        
        # Check if tools are required in the plan
        requires_tools = plan.get("requires_tools", [])
        if requires_tools:
            # If web search is needed, use researcher
            if "web_search" in requires_tools or "search" in requires_tools:
                logger.info(f"Selected ResearcherAgent (tools required): {mission_goal[:50]}...")
                return "researcher"
            
            # If code execution is needed, use developer
            if "code_execution" in requires_tools or "python" in requires_tools:
                logger.info(f"Selected DeveloperAgent (tools required): {mission_goal[:50]}...")
                return "developer"
            
            # Default to researcher for other tool-using missions
            logger.info(f"Selected ResearcherAgent (default for tools): {mission_goal[:50]}...")
            return "researcher"
        
        # Default to simple execution (no specialized agent)
        logger.info(f"Selected simple execution for mission: {mission_goal[:50]}...")
        return "simple"
    
    def get_agent_capabilities(self, agent_type: str) -> Dict[str, Any]:
        """
        Get capabilities and metadata for an agent type.
        
        Args:
            agent_type: Type of agent
            
        Returns:
            Dictionary with agent capabilities and metadata
        """
        capabilities = {
            "researcher": {
                "type": "researcher",
                "name": "Researcher",
                "description": "Conducts research, gathers information, and synthesizes findings from multiple sources",
                "capabilities": [
                    "web_search",
                    "multi_source_synthesis",
                    "fact_verification",
                    "citation_management"
                ],
                "tools": ["web_search", "calculator"],
                "reasoning": "LangGraph workflow with 7 max iterations",
                "use_cases": [
                    "Research topics and gather information",
                    "Find and synthesize data from multiple sources",
                    "Verify facts and cross-reference claims",
                    "Generate research reports with citations"
                ]
            },
            "analyst": {
                "type": "analyst",
                "name": "Analyst",
                "description": "Analyzes data, identifies patterns, and generates actionable insights",
                "capabilities": [
                    "data_analysis",
                    "statistical_calculations",
                    "pattern_recognition",
                    "trend_identification"
                ],
                "tools": ["calculator", "python_executor"],
                "reasoning": "LangGraph workflow with 5 max iterations",
                "use_cases": [
                    "Analyze datasets and identify trends",
                    "Perform statistical calculations",
                    "Generate insights from data",
                    "Compare and evaluate options"
                ]
            },
            "developer": {
                "type": "developer",
                "name": "Developer",
                "description": "Generates code, debugs issues, and writes tests",
                "capabilities": [
                    "code_generation",
                    "debugging",
                    "test_generation",
                    "code_review"
                ],
                "tools": ["python_executor", "file_reader", "file_writer"],
                "reasoning": "LangGraph workflow with 5 max iterations",
                "use_cases": [
                    "Generate code based on specifications",
                    "Debug and fix code issues",
                    "Write unit tests",
                    "Review code and provide feedback"
                ]
            }
        }
        
        return capabilities.get(agent_type.lower(), {})
    
    def list_agent_types(self) -> Dict[str, Any]:
        """
        List all available specialized agent types with their capabilities.
        
        Returns:
            Dictionary with all agent types and their metadata
        """
        return {
            "specialized_agents": [
                self.get_agent_capabilities("researcher"),
                self.get_agent_capabilities("analyst"),
                self.get_agent_capabilities("developer")
            ]
        }
