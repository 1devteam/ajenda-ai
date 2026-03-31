from __future__ import annotations

import logging
from collections.abc import Mapping, MutableMapping
from typing import Any

from pythonjsonlogger.json import JsonFormatter

from backend.app.config import Settings


class RedactionFilter(logging.Filter):
    """Redacts sensitive keys from structured log payloads."""

    def __init__(self, keys_to_redact: set[str]) -> None:
        super().__init__()
        self._keys_to_redact = {key.lower() for key in keys_to_redact}

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "payload") and isinstance(record.payload, MutableMapping):
            record.payload = self._redact_mapping(record.payload)
        if hasattr(record, "extra_data") and isinstance(record.extra_data, MutableMapping):
            record.extra_data = self._redact_mapping(record.extra_data)
        return True

    def _redact_mapping(self, value: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        for key, item in list(value.items()):
            if key.lower() in self._keys_to_redact:
                value[key] = "***REDACTED***"
            elif isinstance(item, MutableMapping):
                value[key] = self._redact_mapping(item)
            elif isinstance(item, list):
                value[key] = [self._redact_item(v) for v in item]
        return value

    def _redact_item(self, item: Any) -> Any:
        if isinstance(item, MutableMapping):
            return self._redact_mapping(item)
        return item


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if hasattr(record, "payload") and isinstance(record.payload, Mapping):
            record.msg = f"{record.msg} payload={dict(record.payload)}"
        return super().format(record)


def configure_logging(settings: Settings) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler()
    handler.addFilter(RedactionFilter(settings.redact_key_set))

    if settings.log_json:
        formatter: logging.Formatter = JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    else:
        formatter = PlainFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
