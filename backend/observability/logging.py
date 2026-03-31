from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from backend.observability.context import get_correlation_id


SENSITIVE_KEYS = {
    "password",
    "secret",
    "token",
    "api_key",
    "authorization",
    "cookie",
    "set-cookie",
}


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        category = getattr(record, "category", None)
        if category is not None:
            payload["category"] = category
        extra_payload = getattr(record, "payload", None)
        if isinstance(extra_payload, dict):
            payload["payload"] = _redact(extra_payload)
        return json.dumps(payload, sort_keys=True)



def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                redacted[key] = "***REDACTED***"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


@dataclass(slots=True)
class ObservabilityLogger:
    logger: logging.Logger

    def info(self, message: str, *, category: str, payload: dict[str, Any] | None = None) -> None:
        self.logger.info(message, extra={"category": category, "payload": payload or {}})

    def warning(self, message: str, *, category: str, payload: dict[str, Any] | None = None) -> None:
        self.logger.warning(message, extra={"category": category, "payload": payload or {}})

    def error(self, message: str, *, category: str, payload: dict[str, Any] | None = None) -> None:
        self.logger.error(message, extra={"category": category, "payload": payload or {}})



def get_observability_logger(name: str) -> ObservabilityLogger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(logging.INFO)
    return ObservabilityLogger(logger)
