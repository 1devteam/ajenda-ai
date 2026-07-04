from __future__ import annotations

import re
from pathlib import Path

from backend.services.operating_charter import (
    DEFAULT_MAY_PERFORM,
    DEFAULT_MAY_PREPARE,
    DEFAULT_NEVER_DO,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_CHARTER = REPO_ROOT / "frontend" / "src" / "config" / "operatingCharter.ts"

_LIST_BLOCK_RE = re.compile(r"(may_prepare|may_perform|never_do):\s*\[([^\]]*)\]", re.MULTILINE)


def _parse_ts_string_list(block: str) -> tuple[str, ...]:
    return tuple(re.findall(r'"([^"]+)"', block))


def _frontend_default_lists() -> dict[str, tuple[str, ...]]:
    text = FRONTEND_CHARTER.read_text(encoding="utf-8")
    match = _LIST_BLOCK_RE.search(text)
    if match is None:
        raise AssertionError("DEFAULT_OPERATING_CHARTER block not found in operatingCharter.ts")
    start = match.start()
    block = text[start : text.find("};", start)]
    parsed: dict[str, tuple[str, ...]] = {}
    for field in ("may_prepare", "may_perform", "never_do"):
        field_match = re.search(rf"{field}:\s*\[([^\]]*)\]", block)
        assert field_match is not None, f"missing {field} in DEFAULT_OPERATING_CHARTER"
        parsed[field] = _parse_ts_string_list(field_match.group(1))
    return parsed


def test_frontend_default_charter_matches_backend() -> None:
    frontend = _frontend_default_lists()
    assert frontend["may_prepare"] == DEFAULT_MAY_PREPARE
    assert frontend["may_perform"] == DEFAULT_MAY_PERFORM
    assert frontend["never_do"] == DEFAULT_NEVER_DO
