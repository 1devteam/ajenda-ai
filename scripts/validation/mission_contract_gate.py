#!/usr/bin/env python3
"""Validate the versioned natural-language mission contract corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO_ROOT / "docs/contracts/mission-interpreter-corpus.v1.json"
DEFAULT_OUTPUT = REPO_ROOT / "artifacts/mission-contract-gate.json"
sys.path.insert(0, str(REPO_ROOT))

from backend.services.mission_composition.intent_interpreter import interpret_instruction  # noqa: E402


def _check_case(case: dict[str, Any]) -> dict[str, Any]:
    instruction = str(case.get("instruction") or "")
    intent = interpret_instruction(instruction)
    expected_outcomes = set(case.get("expected_outcomes") or [])
    actual_outcomes = set(intent.requested_outcomes)
    failures: list[str] = []
    if actual_outcomes != expected_outcomes:
        failures.append(f"outcomes expected={sorted(expected_outcomes)} actual={sorted(actual_outcomes)}")
    expected_quantity = case.get("quantity")
    if intent.requested_quantity != expected_quantity:
        failures.append(f"quantity expected={expected_quantity!r} actual={intent.requested_quantity!r}")
    target = case.get("target") or {}
    entity = intent.target_entities[0] if intent.target_entities else None
    if target:
        if entity is None:
            failures.append("target entity was not extracted")
        else:
            for field in ("industry", "location"):
                expected = target.get(field)
                actual = getattr(entity, field, None)
                if expected and actual != expected:
                    failures.append(f"target.{field} expected={expected!r} actual={actual!r}")
        if len(intent.target_entities) != 1:
            failures.append(f"target entity count expected=1 actual={len(intent.target_entities)}")
    expected_policy = case.get("send_policy")
    if expected_policy and intent.send_policy.mode != expected_policy:
        failures.append(f"send_policy expected={expected_policy!r} actual={intent.send_policy.mode!r}")
    if intent.unmatched_material_clauses:
        failures.append("unmatched=" + "; ".join(item.text for item in intent.unmatched_material_clauses))
    if intent.ambiguity:
        failures.append("ambiguity=" + "; ".join(item.field for item in intent.ambiguity))
    return {
        "id": case.get("id"),
        "status": "passed" if not failures else "failed",
        "failure_reasons": failures,
        "actual": {
            "outcomes": intent.requested_outcomes,
            "quantity": intent.requested_quantity,
            "target": [
                {"industry": item.industry, "location": item.location, "name": item.name}
                for item in intent.target_entities
            ],
            "send_policy": intent.send_policy.mode,
            "unmatched": [item.text for item in intent.unmatched_material_clauses],
            "ambiguity": [item.field for item in intent.ambiguity],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    cases = corpus.get("cases") if isinstance(corpus, dict) else None
    if not isinstance(cases, list) or not cases:
        raise SystemExit("mission corpus must contain a non-empty cases list")
    results = [_check_case(case) for case in cases if isinstance(case, dict)]
    failed = [result for result in results if result["status"] != "passed"]
    report = {
        "schema_version": 1,
        "corpus": str(args.corpus.relative_to(REPO_ROOT)),
        "case_count": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Mission contract gate: {report['passed']}/{report['case_count']} cases passed")
    if failed:
        for result in failed:
            print(f"FAIL {result['id']}: {'; '.join(result['failure_reasons'])}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
