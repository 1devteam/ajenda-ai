"""Error status mapping for mission composition routes."""

from __future__ import annotations

import pytest

from backend.api.routes.mission_composition import _map_error
from backend.services.mission_composition.service import MissionCompositionError


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("INTERPRETER_UNAVAILABLE", 503),
        ("INTERPRETER_TIMEOUT", 503),
        ("INTERPRETER_DISABLED", 503),
        ("INTERPRETER_INVALID_OUTPUT", 503),
        ("INTERPRETER_UNGROUNDED_OUTPUT", 422),
        ("INTERPRETER_DROPPED_QUANTITY", 422),
        ("INTERPRETER_DROPPED_RECIPIENT", 422),
        ("INTERPRETER_INVENTED_URL", 422),
        ("INSTRUCTION_TOO_LONG", 422),
        ("PROPOSAL_NOT_FOUND", 404),
        ("QUOTA_EXCEEDED", 402),
    ],
)
def test_map_error_status_codes(code: str, status: int) -> None:
    exc = MissionCompositionError(code=code, message="detail")
    mapped = _map_error(exc)
    assert mapped.status_code == status
    assert mapped.detail == {"code": code, "message": "detail"}
