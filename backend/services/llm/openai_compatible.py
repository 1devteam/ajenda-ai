from __future__ import annotations

import httpx

from backend.app.config import Settings
from backend.services.llm.contracts import LlmGenerateRequest, LlmGenerateResult


class OpenAiCompatibleLlm:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def generate(self, request: LlmGenerateRequest) -> LlmGenerateResult:
        api_key = str(self._settings.llm_api_key or "").strip()
        if not api_key:
            raise ValueError("LLM API key is not configured")

        base_url = str(self._settings.llm_base_url).rstrip("/")
        model = str(self._settings.llm_model).strip()
        payload = {
            "model": model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        timeout = float(self._settings.llm_timeout_seconds)
        with httpx.Client(timeout=timeout) as client:
            response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("LLM response missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ValueError("LLM response choice is invalid")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ValueError("LLM response message is invalid")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("LLM response content is empty")

        return LlmGenerateResult(
            text=content.strip(),
            provider="openai_compatible",
            model=model,
            used_llm=True,
        )
