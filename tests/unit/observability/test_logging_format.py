import json
import logging

from backend.observability.context import set_correlation_id
from backend.observability.logging import StructuredFormatter


def test_structured_formatter_includes_correlation_id_and_redacts() -> None:
    set_correlation_id("req-1")
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "hello", (), None)
    record.category = "runtime"
    record.payload = {"token": "secret", "nested": {"password": "pw"}}
    output = StructuredFormatter().format(record)
    payload = json.loads(output)
    assert payload["correlation_id"] == "req-1"
    assert payload["payload"]["token"] == "***REDACTED***"
