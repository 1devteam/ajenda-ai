"""
LLM Metrics Wrapper
Wraps any LangChain BaseChatModel to record Prometheus metrics automatically.

Built with Pride for Obex Blackvault

Note on LangChain 0.3.x compatibility:
  AsyncCallbackManagerForLLMRun.get_child() was removed in langchain-core ≥ 0.3.
  We now delegate directly to the underlying LLM's ainvoke/invoke rather than
  calling agenerate/generate with a child callback manager.
"""

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

    Records:
    - Token usage (prompt, completion, total)
    - Latency (total duration)
    - Error rates per provider

    Compatible with langchain-core >= 0.3 (get_child() removed).
    """

    llm_instance: Any = Field(description="The underlying LLM instance")
    provider: str = Field(description="The LLM provider name")
    model_name: str = Field(description="The model name")

    def __init__(self, llm: BaseChatModel, provider: str, model_name: str, **kwargs):
        super().__init__(llm_instance=llm, provider=provider, model_name=model_name, **kwargs)

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Synchronous generation with metrics recording."""
        start_time = time.time()
        try:
            # Delegate to the underlying LLM's _generate directly to avoid
            # the removed get_child() call on the callback manager.
            result = self.llm_instance._generate(messages, stop=stop, **kwargs)
            duration = time.time() - start_time
            self._record_metrics(result, duration)
            return result
        except Exception as exc:
            get_metrics().record_system_error(f"llm_error_{self.provider}")
            raise exc

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Asynchronous generation with metrics recording."""
        start_time = time.time()
        try:
            # Delegate to the underlying LLM's _agenerate directly.
            # We intentionally do NOT pass run_manager.get_child() because
            # get_child() was removed in langchain-core 0.3.x.
            result = await self.llm_instance._agenerate(messages, stop=stop, **kwargs)
            duration = time.time() - start_time
            self._record_metrics(result, duration)
            return result
        except Exception as exc:
            get_metrics().record_system_error(f"llm_error_{self.provider}")
            raise exc

    def _record_metrics(self, result: ChatResult, duration: float) -> None:
        """Record Prometheus metrics for a completed LLM call."""
        token_usage = result.llm_output.get("token_usage", {}) if result.llm_output else {}
        get_metrics().record_llm_call(
            provider=self.provider,
            model=self.model_name,
            prompt_tokens=token_usage.get("prompt_tokens", 0),
            completion_tokens=token_usage.get("completion_tokens", 0),
            cost_usd=0.0,  # Cost calculation can be added per-provider later
            latency_seconds=duration,
        )

    @property
    def _llm_type(self) -> str:
        return f"metrics_wrapper_{self.llm_instance._llm_type}"
