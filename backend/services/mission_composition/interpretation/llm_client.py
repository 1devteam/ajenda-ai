"""OpenAI-compatible structured-output client for the local interpreter model."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from backend.app.config import Settings
from backend.observability.logging import get_observability_logger
from backend.services.mission_composition.interpretation.schema import LlmMissionInterpretation

_LOG = get_observability_logger(__name__)


class MissionInterpreterTransportError(RuntimeError):
    def __init__(self, *, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class MissionInterpretationRequest:
    system_prompt: str
    user_prompt: str


class MissionInterpreterClient(Protocol):
    model: str

    def interpret(self, request: MissionInterpretationRequest) -> LlmMissionInterpretation: ...


class OpenAiCompatibleMissionInterpreterClient:
    """Calls Ollama, llama.cpp, or another internal OpenAI-compatible server.

    This client is intentionally strict: it has no template or unstructured
    fallback. Transport, protocol, JSON, and schema failures remain visible and
    fail closed at the composition boundary.
    """

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        self.model = str(settings.mission_interpreter_model).strip()

    def interpret(self, request: MissionInterpretationRequest) -> LlmMissionInterpretation:
        if not self._settings.mission_interpreter_enabled:
            raise MissionInterpreterTransportError(
                code="INTERPRETER_DISABLED",
                message="mission interpretation is not enabled",
                retryable=False,
            )
        base_url = str(self._settings.mission_interpreter_base_url).strip().rstrip("/")
        if not base_url or not self.model:
            raise MissionInterpreterTransportError(
                code="INTERPRETER_NOT_CONFIGURED",
                message="mission interpreter endpoint and model must be configured",
                retryable=False,
            )

        schema = LlmMissionInterpretation.model_json_schema()
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": int(self._settings.mission_interpreter_max_tokens),
            "stream": False,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "ajenda_mission_interpretation",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        headers = {"Content-Type": "application/json"}
        api_key = str(self._settings.mission_interpreter_api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        started = time.monotonic()
        try:
            # The endpoint is an operator-configured private service. Ignore ambient
            # HTTP(S)_PROXY variables so raw mission wording is never forwarded to
            # a workstation or cluster proxy by accident.
            with httpx.Client(
                timeout=float(self._settings.mission_interpreter_timeout_seconds),
                trust_env=False,
            ) as client:
                response = client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.TimeoutException as exc:
            self._log_failure(code="INTERPRETER_TIMEOUT", started=started, retryable=True)
            raise MissionInterpreterTransportError(
                code="INTERPRETER_TIMEOUT",
                message="mission interpretation timed out; try again",
                retryable=True,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            self._log_failure(code="INTERPRETER_UNAVAILABLE", started=started, retryable=True)
            raise MissionInterpreterTransportError(
                code="INTERPRETER_UNAVAILABLE",
                message="mission interpretation is temporarily unavailable; try again",
                retryable=True,
            ) from exc

        try:
            content = _response_content(body)
            interpretation = LlmMissionInterpretation.model_validate_json(content)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._log_failure(code="INTERPRETER_INVALID_OUTPUT", started=started, retryable=True)
            raise MissionInterpreterTransportError(
                code="INTERPRETER_INVALID_OUTPUT",
                message="mission interpretation could not be validated; revise or try again",
                retryable=True,
            ) from exc

        _LOG.info(
            "mission interpretation completed",
            category="mission_interpreter",
            payload={
                "model": self.model,
                "status": "success",
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
                "schema_version": interpretation.schema_version,
            },
        )
        return interpretation

    def _log_failure(self, *, code: str, started: float, retryable: bool) -> None:
        _LOG.warning(
            "mission interpretation failed",
            category="mission_interpreter",
            payload={
                "model": self.model,
                "status": "failure",
                "code": code,
                "retryable": retryable,
                "latency_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )


def _response_content(body: Any) -> str:
    if not isinstance(body, dict):
        raise TypeError("interpreter response must be an object")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("interpreter response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise TypeError("interpreter response choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise TypeError("interpreter response message must be an object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("interpreter response content is empty")
    return content.strip()
