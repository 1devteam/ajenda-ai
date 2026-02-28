"""
LLM Provider Factory for Omnipath v3.0

Provides a unified interface for creating LLM instances from multiple providers:
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude 3.5, Claude 3)
- Google (Gemini 2.0, Gemini 1.5)
- xAI (Grok)
- Ollama (Local open-source models)

Supports easy model switching via configuration.
"""

from typing import Optional
from enum import Enum
from langchain_core.language_models import BaseChatModel
from backend.integrations.llm.llm_metrics_wrapper import LLMMetricsWrapper


class LLMProvider(str, Enum):
    """Supported LLM providers"""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    XAI = "xai"  # Grok
    OLLAMA = "ollama"


class LLMFactory:
    """Factory for creating LLM instances with easy provider switching"""

    # Default models for each provider
    DEFAULT_MODELS = {
        LLMProvider.OPENAI: "gpt-4-turbo",
        LLMProvider.ANTHROPIC: "claude-3-5-sonnet-20241022",
        LLMProvider.GOOGLE: "gemini-2.0-flash-exp",
        LLMProvider.XAI: "grok-beta",
        LLMProvider.OLLAMA: "llama3.1:70b",
    }

    @staticmethod
    def create_llm(
        provider: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs,
    ) -> BaseChatModel:
        """
        Create an LLM instance from the specified provider.

        Args:
            provider: Provider name (openai, anthropic, google, xai, ollama)
            model: Model name (uses default if not specified)
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate
            api_key: API key for the provider
            base_url: Base URL for API (for Ollama or custom endpoints)
            **kwargs: Additional provider-specific arguments

        Returns:
            BaseChatModel: Configured LLM instance
        """
        provider = provider.lower()

        # Use default model if not specified
        if model is None:
            model = LLMFactory.DEFAULT_MODELS.get(provider)

        if provider == LLMProvider.OPENAI:
            llm = LLMFactory._create_openai(model, temperature, max_tokens, api_key, **kwargs)

        elif provider == LLMProvider.ANTHROPIC:
            llm = LLMFactory._create_anthropic(model, temperature, max_tokens, api_key, **kwargs)

        elif provider == LLMProvider.GOOGLE:
            llm = LLMFactory._create_google(model, temperature, max_tokens, api_key, **kwargs)

        elif provider == LLMProvider.XAI:
            llm = LLMFactory._create_xai(model, temperature, max_tokens, api_key, **kwargs)

        elif provider == LLMProvider.OLLAMA:
            llm = LLMFactory._create_ollama(model, temperature, max_tokens, base_url, **kwargs)

        else:
            raise ValueError(f"Unsupported provider: {provider}")

        # Wrap the LLM to record metrics
        return LLMMetricsWrapper(llm=llm, provider=provider, model_name=model)

    @staticmethod
    def _create_openai(
        model: str,
        temperature: float,
        max_tokens: Optional[int],
        api_key: Optional[str],
        **kwargs,
    ) -> BaseChatModel:
        """Create OpenAI LLM instance"""
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            **kwargs,
        )

    @staticmethod
    def _create_anthropic(
        model: str,
        temperature: float,
        max_tokens: Optional[int],
        api_key: Optional[str],
        **kwargs,
    ) -> BaseChatModel:
        """Create Anthropic (Claude) LLM instance"""
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            **kwargs,
        )

    @staticmethod
    def _create_google(
        model: str,
        temperature: float,
        max_tokens: Optional[int],
        api_key: Optional[str],
        **kwargs,
    ) -> BaseChatModel:
        """Create Google (Gemini) LLM instance"""
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            max_output_tokens=max_tokens,
            google_api_key=api_key,
            **kwargs,
        )

    @staticmethod
    def _create_xai(
        model: str,
        temperature: float,
        max_tokens: Optional[int],
        api_key: Optional[str],
        **kwargs,
    ) -> BaseChatModel:
        """Create xAI (Grok) LLM instance"""
        from langchain_openai import ChatOpenAI

        # Grok uses OpenAI-compatible API
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url="https://api.x.ai/v1",
            **kwargs,
        )

    @staticmethod
    def _create_ollama(
        model: str,
        temperature: float,
        max_tokens: Optional[int],
        base_url: Optional[str],
        **kwargs,
    ) -> BaseChatModel:
        """Create Ollama (local) LLM instance"""
        from langchain_ollama import ChatOllama

        if base_url is None:
            base_url = "http://localhost:11434"

        return ChatOllama(
            model=model,
            temperature=temperature,
            num_predict=max_tokens,
            base_url=base_url,
            **kwargs,
        )


class ModelConfig:
    """Configuration for a specific model"""

    def __init__(
        self,
        provider: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ):
        self.provider = provider
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.kwargs = kwargs

    def create_llm(
        self, api_key: Optional[str] = None, base_url: Optional[str] = None
    ) -> BaseChatModel:
        """Create an LLM instance from this configuration"""
        return LLMFactory.create_llm(
            provider=self.provider,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            api_key=api_key,
            base_url=base_url,
            **self.kwargs,
        )
