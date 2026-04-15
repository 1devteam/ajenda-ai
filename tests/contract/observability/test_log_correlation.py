import json
import logging

from backend.observability.context import set_correlation_id
from backend.observability.logging import StructuredFormatter


def test_log_correlation_is_propagated() -> None:
    set_correlation_id("corr-123")
    record = logging.LogRecord("obs", logging.INFO, __file__, 1, "message", (), None)
    output = StructuredFormatter().format(record)
    payload = json.loads(output)
    assert payload["correlation_id"] == "corr-123"
