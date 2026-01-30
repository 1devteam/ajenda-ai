"""
Enhanced Base Agent with Multi-Model LLM Support
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime
from langchain_core.language_models import BaseChatModel

from backend.config.settings import settings
from backend.integrations.llm import LLMFactory


class AgentState(str, Enum):
    """Agent lifecycle states"""
    PENDING = "pending"
    VALIDATING = "validating"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


class BaseAgentV3(ABC):
    """
    Enhanced base agent with multi-model LLM support.
    
    Features:
    - Easy model switching via configuration
    - Support for multiple LLM providers
    - State machine lifecycle
    - Event sourcing integration
    """
    
    def __init__(
        self,
        agent_id: str,
        agent_type: str,
        tenant_id: str,
        mission_payload: Dict[str, Any],
        configuration: Optional[Dict[str, Any]] = None
    ):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.tenant_id = tenant_id
        self.mission_payload = mission_payload
        self.configuration = configuration or {}
        
        self.state = AgentState.PENDING
        self.created_at = datetime.utcnow()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.error_message: Optional[str] = None
        
        # LLM instance (created lazily)
        self._llm: Optional[BaseChatModel] = None
    
    @property
    def llm(self) -> BaseChatModel:
        """
        Get or create the LLM instance for this agent.
        Uses configuration from settings based on agent type.
        """
        if self._llm is None:
            self._llm = self._create_llm()
        return self._llm
    
    def _create_llm(self) -> BaseChatModel:
        """
        Create LLM instance based on agent type and configuration.
        Can be overridden by subclasses for custom behavior.
        """
        # Get provider and model from settings based on agent type
        provider, model, temperature = self._get_llm_config()
        
        # Get API key based on provider
        api_key = self._get_api_key(provider)
        
        # Create LLM instance
        return LLMFactory.create_llm(
            provider=provider,
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=settings.OLLAMA_BASE_URL if provider == "ollama" else None
        )
    
    def _get_llm_config(self) -> tuple[str, str, float]:
        """Get LLM configuration based on agent type"""
        agent_type_lower = self.agent_type.lower()
        
        if "commander" in agent_type_lower:
            return (
                settings.COMMANDER_PROVIDER,
                settings.COMMANDER_MODEL,
                settings.COMMANDER_TEMPERATURE
            )
        elif "guardian" in agent_type_lower:
            return (
                settings.GUARDIAN_PROVIDER,
                settings.GUARDIAN_MODEL,
                settings.GUARDIAN_TEMPERATURE
            )
        elif "archivist" in agent_type_lower:
            return (
                settings.ARCHIVIST_PROVIDER,
                settings.ARCHIVIST_MODEL,
                settings.ARCHIVIST_TEMPERATURE
            )
        else:
            # Default to fork agent config
            return (
                settings.FORK_PROVIDER,
                settings.FORK_MODEL,
                settings.FORK_TEMPERATURE
            )
    
    def _get_api_key(self, provider: str) -> Optional[str]:
        """Get API key for the specified provider"""
        provider_key_map = {
            "openai": settings.OPENAI_API_KEY,
            "anthropic": settings.ANTHROPIC_API_KEY,
            "google": settings.GOOGLE_API_KEY,
            "xai": settings.XAI_API_KEY,
            "ollama": None  # No API key needed for local Ollama
        }
        return provider_key_map.get(provider.lower())
    
    def switch_model(self, provider: str, model: Optional[str] = None, temperature: Optional[float] = None):
        """
        Switch to a different LLM model at runtime.
        
        Args:
            provider: New provider (openai, anthropic, google, xai, ollama)
            model: New model name (optional, uses provider default)
            temperature: New temperature (optional, keeps current)
        """
        api_key = self._get_api_key(provider)
        
        if temperature is None:
            _, _, temperature = self._get_llm_config()
        
        self._llm = LLMFactory.create_llm(
            provider=provider,
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=settings.OLLAMA_BASE_URL if provider == "ollama" else None
        )
    
    async def execute(self) -> Dict[str, Any]:
        """
        Execute the agent's mission.
        Implements the full state machine lifecycle.
        """
        try:
            # Validate
            self.state = AgentState.VALIDATING
            await self.validate()
            
            # Initialize
            self.state = AgentState.INITIALIZING
            await self.initialize()
            
            # Run
            self.state = AgentState.RUNNING
            self.started_at = datetime.utcnow()
            result = await self.run()
            
            # Complete
            self.state = AgentState.COMPLETED
            self.completed_at = datetime.utcnow()
            
            return result
            
        except Exception as e:
            self.state = AgentState.FAILED
            self.error_message = str(e)
            self.completed_at = datetime.utcnow()
            raise
    
    @abstractmethod
    async def validate(self):
        """Validate mission parameters and preconditions"""
        pass
    
    @abstractmethod
    async def initialize(self):
        """Initialize agent resources and state"""
        pass
    
    @abstractmethod
    async def run(self) -> Dict[str, Any]:
        """Execute the agent's core logic"""
        pass
    
    async def shutdown(self):
        """Clean up agent resources"""
        self.state = AgentState.TERMINATED
