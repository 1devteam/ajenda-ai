"""
LLM Service Layer
Manages LLM access with configuration, caching, and error handling

Built with Pride for Obex Blackvault
"""
from typing import Optional, Dict
from langchain_core.language_models import BaseChatModel
import logging

from backend.integrations.llm.llm_factory import LLMFactory
from backend.config.settings import Settings

logger = logging.getLogger(__name__)


class LLMService:
    """
    Service layer for LLM access with configuration management
    
    Responsibilities:
    - Map agent types to LLM providers/models
    - Cache LLM instances for reuse
    - Handle API key management
    - Provide fallback mechanisms
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize LLM Service
        
        Args:
            settings: Application settings with LLM configuration
        """
        self.settings = settings
        self._llm_cache: Dict[str, BaseChatModel] = {}
        logger.info("LLM Service initialized")
    
    def get_llm(self, agent_type: str, tenant_id: str) -> BaseChatModel:
        """
        Get LLM for specific agent type
        
        Args:
            agent_type: "commander", "guardian", "archivist", "fork", "custom"
            tenant_id: Tenant identifier (for future per-tenant config)
        
        Returns:
            Configured LLM instance
            
        Raises:
            ValueError: If agent_type is invalid or provider not configured
        """
        # Normalize agent type
        agent_type = agent_type.lower()
        
        # Get provider and model from settings
        provider_key = f"{agent_type.upper()}_PROVIDER"
        model_key = f"{agent_type.upper()}_MODEL"
        temp_key = f"{agent_type.upper()}_TEMPERATURE"
        
        provider = getattr(self.settings, provider_key, None)
        model = getattr(self.settings, model_key, None)
        temperature = getattr(self.settings, temp_key, 0.7)
        
        # Fallback to OpenAI if not configured
        if not provider:
            logger.warning(f"No provider configured for {agent_type}, using OpenAI")
            provider = "openai"
            model = "gpt-3.5-turbo"
        
        # Get API key
        api_key = self._get_api_key(provider)
        
        # Validate API key (except for Ollama)
        if provider != "ollama" and not api_key:
            raise ValueError(
                f"No API key configured for provider '{provider}'. "
                f"Set {provider.upper()}_API_KEY environment variable."
            )
        
        # Cache key
        cache_key = f"{tenant_id}:{agent_type}:{provider}:{model}"
        
        # Return cached instance if available
        if cache_key in self._llm_cache:
            logger.debug(f"Using cached LLM: {cache_key}")
            return self._llm_cache[cache_key]
        
        # Create new LLM instance
        try:
            logger.info(f"Creating LLM: provider={provider}, model={model}, agent_type={agent_type}")
            
            # Set default max_tokens based on provider
            # Anthropic requires max_tokens to be set
            max_tokens = 4096  # Default for most providers
            if provider == "anthropic":
                max_tokens = 4096  # Claude's default
            elif provider == "openai":
                max_tokens = None  # OpenAI allows None (uses model default)
            elif provider == "google":
                max_tokens = 8192  # Gemini's default
            elif provider == "xai":
                max_tokens = None  # Grok uses OpenAI-compatible API
            elif provider == "ollama":
                max_tokens = 2048  # Local models default
            
            llm = LLMFactory.create_llm(
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=api_key
            )
            
            # Cache for reuse
            self._llm_cache[cache_key] = llm
            
            return llm
            
        except Exception as e:
            logger.error(f"Failed to create LLM for {agent_type}: {e}")
            raise ValueError(f"Failed to create LLM: {str(e)}")
    
    def get_llm_by_model(self, model_name: str, tenant_id: str, temperature: float = 0.7) -> BaseChatModel:
        """
        Get LLM by specific model name
        
        Useful when Commander selects a specific model for a task.
        
        Args:
            model_name: Specific model name (e.g., "gpt-4", "claude-3-5-sonnet")
            tenant_id: Tenant identifier
            temperature: Temperature setting (0.0-1.0)
        
        Returns:
            Configured LLM instance
            
        Raises:
            ValueError: If model not supported or provider not configured
        """
        # Determine provider from model name
        provider = self._infer_provider(model_name)
        api_key = self._get_api_key(provider)
        
        # Validate API key
        if provider != "ollama" and not api_key:
            raise ValueError(
                f"No API key configured for provider '{provider}'. "
                f"Set {provider.upper()}_API_KEY environment variable."
            )
        
        # Cache key
        cache_key = f"{tenant_id}:custom:{provider}:{model_name}:{temperature}"
        
        # Return cached instance if available
        if cache_key in self._llm_cache:
            logger.debug(f"Using cached LLM: {cache_key}")
            return self._llm_cache[cache_key]
        
        # Create new LLM instance
        try:
            logger.info(f"Creating custom LLM: provider={provider}, model={model_name}")
            
            # Set default max_tokens based on provider
            max_tokens = 4096  # Default for most providers
            if provider == "anthropic":
                max_tokens = 4096  # Claude's default
            elif provider == "openai":
                max_tokens = None  # OpenAI allows None
            elif provider == "google":
                max_tokens = 8192  # Gemini's default
            elif provider == "xai":
                max_tokens = None  # Grok uses OpenAI-compatible API
            elif provider == "ollama":
                max_tokens = 2048  # Local models default
            
            llm = LLMFactory.create_llm(
                provider=provider,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=api_key
            )
            
            # Cache for reuse
            self._llm_cache[cache_key] = llm
            
            return llm
            
        except Exception as e:
            logger.error(f"Failed to create LLM for model {model_name}: {e}")
            raise ValueError(f"Failed to create LLM: {str(e)}")
    
    def _get_api_key(self, provider: str) -> Optional[str]:
        """
        Get API key for provider
        
        Args:
            provider: Provider name ("openai", "anthropic", "google", "xai", "ollama")
        
        Returns:
            API key or None for Ollama
        """
        key_map = {
            "openai": self.settings.OPENAI_API_KEY,
            "anthropic": self.settings.ANTHROPIC_API_KEY,
            "google": self.settings.GOOGLE_API_KEY,
            "xai": self.settings.XAI_API_KEY,
            "ollama": None  # Ollama doesn't need API key
        }
        return key_map.get(provider)
    
    def _infer_provider(self, model_name: str) -> str:
        """
        Infer provider from model name
        
        Args:
            model_name: Model name (e.g., "gpt-4", "claude-3-5-sonnet")
        
        Returns:
            Provider name
        """
        model_lower = model_name.lower()
        
        if "gpt" in model_lower or "o1" in model_lower:
            return "openai"
        elif "claude" in model_lower:
            return "anthropic"
        elif "gemini" in model_lower:
            return "google"
        elif "grok" in model_lower:
            return "xai"
        elif "llama" in model_lower or "mistral" in model_lower:
            return "ollama"
        else:
            # Default to OpenAI
            logger.warning(f"Unknown model '{model_name}', defaulting to OpenAI")
            return "openai"
    
    def clear_cache(self):
        """Clear LLM cache (useful for testing or config changes)"""
        self._llm_cache.clear()
        logger.info("LLM cache cleared")
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics"""
        return {
            "cached_llms": len(self._llm_cache),
            "cache_keys": list(self._llm_cache.keys())
        }
