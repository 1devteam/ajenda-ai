import time
from typing import Any, List, Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from langchain_core.callbacks import (
    CallbackManagerForLLMRun,
    AsyncCallbackManagerForLLMRun,
)
from pydantic import Field

from backend.integrations.observability.prometheus_metrics import get_metrics


class LLMMetricsWrapper(BaseChatModel):
    """
    Wrapper for LangChain LLMs to automatically record Prometheus metrics.

    This interceptor records:
    - Token usage (prompt, completion, total)
    - Latency (time to first token, total duration)
    - Error rates
    """

    # Use any to avoid issues with pydantic validation of langchain objects
    llm_instance: Any = Field(description="The underlying LLM instance")
    provider: str = Field(description="The LLM provider name")
    model_name: str = Field(description="The model name")

    def __init__(self, llm: BaseChatModel, provider: str, model_name: str, **kwargs):
        super().__init__(
            llm_instance=llm, provider=provider, model_name=model_name, **kwargs
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        start_time = time.time()

        try:
            # Use generate instead of _generate to ensure all callbacks and logic run
            result = self.llm_instance.generate(
                [messages],
                stop=stop,
                callbacks=run_manager.get_child() if run_manager else None,
                **kwargs,
            )

            duration = time.time() - start_time

            # Record metrics
            token_usage = (
                result.llm_output.get("token_usage", {}) if result.llm_output else {}
            )
            # Estimate cost (simplified)
            cost = 0.0

            get_metrics().record_llm_call(
                provider=self.provider,
                model=self.model_name,
                prompt_tokens=token_usage.get("prompt_tokens", 0),
                completion_tokens=token_usage.get("completion_tokens", 0),
                cost_usd=cost,
                latency_seconds=duration,
            )

            # Convert LLMResult generation to ChatResult
            return ChatResult(
                generations=result.generations[0], llm_output=result.llm_output
            )

        except Exception as e:
            get_metrics().record_system_error(f"llm_error_{self.provider}")
            raise e

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        start_time = time.time()

        try:
            result = await self.llm_instance.agenerate(
                [messages],
                stop=stop,
                callbacks=run_manager.get_child() if run_manager else None,
                **kwargs,
            )

            duration = time.time() - start_time

            # Record metrics
            token_usage = (
                result.llm_output.get("token_usage", {}) if result.llm_output else {}
            )
            # Estimate cost (simplified)
            cost = 0.0

            get_metrics().record_llm_call(
                provider=self.provider,
                model=self.model_name,
                prompt_tokens=token_usage.get("prompt_tokens", 0),
                completion_tokens=token_usage.get("completion_tokens", 0),
                cost_usd=cost,
                latency_seconds=duration,
            )

            return ChatResult(
                generations=result.generations[0], llm_output=result.llm_output
            )

        except Exception as e:
            get_metrics().record_system_error(f"llm_error_{self.provider}")
            raise e

    @property
    def _llm_type(self) -> str:
        return f"metrics_wrapper_{self.llm_instance._llm_type}"
