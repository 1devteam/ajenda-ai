from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.services.tools.schemas import EvidenceItem, HttpRequestInput, ToolInvocationEnvelope


def test_tool_invocation_envelope_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        ToolInvocationEnvelope.model_validate({"schema_version": 2, "action": "record.search"})


def test_evidence_item_requires_non_empty_summary() -> None:
    with pytest.raises(ValidationError, match="summary"):
        EvidenceItem(evidence_type="action_result", evidence_source="tool.invoke.test", summary="   ")


def test_http_request_input_rejects_relative_url() -> None:
    with pytest.raises(ValidationError, match="absolute http or https URL"):
        HttpRequestInput.model_validate({"url": "/relative"})
