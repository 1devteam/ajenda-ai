from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[3]
MODULE_PATH = ROOT / "scripts/validation/mission_verification_portfolio.py"
SPEC = importlib.util.spec_from_file_location("mission_verification_portfolio", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _portfolio() -> dict:
    return json.loads((ROOT / "docs/validation/mission-verification-portfolio.v1.json").read_text())


def test_portfolio_is_structured_and_marks_unproven_families_explicitly() -> None:
    payload = _portfolio()

    assert MODULE.validate_portfolio(payload) == []
    assert len(payload["missions"]) >= 6
    assert any(item["verification_state"] == "runtime_proven" for item in payload["missions"])
    assert any(item["verification_state"] == "contract_pending" for item in payload["missions"])


def test_portfolio_rejects_allowed_forbidden_action_overlap() -> None:
    payload = _portfolio()
    payload["missions"][0]["forbidden_actions"].append("web.research")

    errors = MODULE.validate_portfolio(payload)

    assert any("both allowed and forbidden" in error for error in errors)
