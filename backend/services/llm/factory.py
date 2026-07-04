from __future__ import annotations

from backend.app.config import Settings, get_settings
from backend.services.llm.contracts import LlmGenerateRequest, LlmGenerateResult
from backend.services.llm.openai_compatible import OpenAiCompatibleLlm


class TemplateFallbackLlm:
    """Deterministic local draft path when no LLM key is configured."""

    def generate(self, request: LlmGenerateRequest) -> LlmGenerateResult:
        return LlmGenerateResult(
            text=request.user_prompt.strip(),
            provider="template_fallback",
            model="template",
            used_llm=False,
        )


def get_llm_provider(*, settings: Settings | None = None) -> OpenAiCompatibleLlm | TemplateFallbackLlm:
    resolved = settings or get_settings()
    if resolved.llm_ready:
        return OpenAiCompatibleLlm(settings=resolved)
    return TemplateFallbackLlm()


def generate_text(*, request: LlmGenerateRequest, settings: Settings | None = None) -> LlmGenerateResult:
    provider = get_llm_provider(settings=settings)
    if isinstance(provider, TemplateFallbackLlm):
        return provider.generate(request)
    try:
        return provider.generate(request)
    except Exception:
        return TemplateFallbackLlm().generate(request)
