from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LlmProviderName = Literal["openai_compatible", "template_fallback"]


@dataclass(frozen=True, slots=True)
class LlmGenerateRequest:
    system_prompt: str
    user_prompt: str
    temperature: float = 0.4
    max_tokens: int = 1200


@dataclass(frozen=True, slots=True)
class LlmGenerateResult:
    text: str
    provider: LlmProviderName
    model: str
    used_llm: bool
