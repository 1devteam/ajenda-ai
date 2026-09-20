#!/usr/bin/env python3
"""Validate the machine-readable real-world mission verification portfolio."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REQUIRED_MISSION_FIELDS = (
    "id",
    "verification_state",
    "observed_gap_codes",
    "request",
    "intent",
    "expected_nodes",
    "expected_artifacts",
    "allowed_actions",
    "forbidden_actions",
    "evidence_requirements",
    "acceptance",
)
ALLOWED_STATES = frozenset({"runtime_proven", "contract_pending", "composition_blocked"})


def validate_portfolio(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    missions = payload.get("missions")
    if not isinstance(missions, list) or not missions:
        return [*errors, "missions must be a non-empty list"]
    seen: set[str] = set()
    for index, mission in enumerate(missions):
        prefix = f"missions[{index}]"
        if not isinstance(mission, dict):
            errors.append(f"{prefix} must be an object")
            continue
        missing = [field for field in REQUIRED_MISSION_FIELDS if field not in mission]
        errors.extend(f"{prefix} missing {field}" for field in missing)
        mission_id = mission.get("id")
        if not isinstance(mission_id, str) or not mission_id:
            errors.append(f"{prefix}.id must be a non-empty string")
        elif mission_id in seen:
            errors.append(f"duplicate mission id: {mission_id}")
        else:
            seen.add(mission_id)
        if mission.get("verification_state") not in ALLOWED_STATES:
            errors.append(f"{prefix}.verification_state is unsupported")
        for field in REQUIRED_MISSION_FIELDS[4:]:
            value = mission.get(field)
            if field in {
                "expected_nodes",
                "expected_artifacts",
                "allowed_actions",
                "forbidden_actions",
                "evidence_requirements",
                "acceptance",
            } and (not isinstance(value, list) or not all(isinstance(item, str) and item for item in value)):
                errors.append(f"{prefix}.{field} must be a list of non-empty strings")
        gaps = mission.get("observed_gap_codes")
        if not isinstance(gaps, list) or not all(isinstance(item, str) and item for item in gaps):
            errors.append(f"{prefix}.observed_gap_codes must be a list of non-empty strings")
        overlap = set(mission.get("allowed_actions") or []) & set(mission.get("forbidden_actions") or [])
        if overlap:
            errors.append(f"{prefix} action appears in both allowed and forbidden: {sorted(overlap)}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portfolio",
        type=Path,
        default=Path("docs/validation/mission-verification-portfolio.v1.json"),
    )
    args = parser.parse_args()
    payload = json.loads(args.portfolio.read_text(encoding="utf-8"))
    errors = validate_portfolio(payload if isinstance(payload, dict) else {})
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    missions = payload["missions"]
    proven = sum(item["verification_state"] == "runtime_proven" for item in missions)
    print(f"Mission verification portfolio: passed ({len(missions)} missions, {proven} runtime-proven)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
