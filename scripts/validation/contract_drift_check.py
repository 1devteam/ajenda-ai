#!/usr/bin/env python3
"""Contract drift sentinel (Bundle 1.2/1.3 foundation).

Checks (warn-mode by default):
1) Tier-1 canonical docs exist.
2) Authority-ledger route coverage for key mission runtime routes.
3) Mixed-method mission routes are represented as method-specific ledger entries.
4) Operator-cue fields exist on all ledger entries.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = REPO_ROOT / "docs/contracts/authority-ledger.v1.yaml"

TIER1_DOCS = [
    "PROJECT_SPEC.md",
    "README.md",
    "docs/architecture/ADR_INDEX.md",
    "docs/validation/live-runtime-matrix.md",
    "docs/validation/live-runtime-proof-release-gate.md",
]

REQUIRED_MISSION_ROUTES = {
    "POST /v1/missions/{mission_id}/materialize-graph",
    "GET /v1/missions/{mission_id}/runtime-admission",
    "POST /v1/missions/{mission_id}/runtime-admission",
    "GET /v1/missions/{mission_id}/runtime-task-materialization",
    "POST /v1/missions/{mission_id}/runtime-task-materialization",
    "POST /v1/missions/{mission_id}/runtime-queue-admission",
    "POST /v1/missions/{mission_id}/queue",
    "GET /v1/missions/{mission_id}/worker-run-admission",
    "POST /v1/missions/{mission_id}/worker-run-admission",
}

OPERATOR_CUE_FIELDS = ["authority_class", "side_effect_class", "allowed_side_effects", "forbidden_side_effects"]


@dataclass
class Finding:
    level: str
    code: str
    message: str


def _load_ledger_text() -> str:
    if not LEDGER_PATH.exists():
        raise FileNotFoundError(f"Ledger not found: {LEDGER_PATH}")
    return LEDGER_PATH.read_text(encoding="utf-8")


def _iter_entries(ledger_text: str) -> Iterable[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    in_route_scope = False
    in_allowed = False
    in_forbidden = False

    for raw in ledger_text.splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("- id:") and line.startswith("  - id:"):
            if current:
                entries.append(current)
            current = {"id": stripped.split(":", 1)[1].strip(), "route_scope": [], "allowed_side_effects": [], "forbidden_side_effects": []}
            in_route_scope = in_allowed = in_forbidden = False
            continue

        if current is None:
            continue

        if stripped.startswith("route_scope:"):
            in_route_scope, in_allowed, in_forbidden = True, False, False
            continue
        if stripped.startswith("allowed_side_effects:"):
            in_route_scope, in_allowed, in_forbidden = False, True, False
            continue
        if stripped.startswith("forbidden_side_effects:"):
            in_route_scope, in_allowed, in_forbidden = False, False, True
            continue

        if stripped.startswith("authority_class:"):
            current["authority_class"] = stripped.split(":", 1)[1].strip()
            continue
        if stripped.startswith("side_effect_class:"):
            current["side_effect_class"] = stripped.split(":", 1)[1].strip()
            continue

        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if in_route_scope:
                current["route_scope"].append(value)
            elif in_allowed:
                current["allowed_side_effects"].append(value)
            elif in_forbidden:
                current["forbidden_side_effects"].append(value)

    if current:
        entries.append(current)
    return entries


def run_checks(strict: bool) -> tuple[list[Finding], int]:
    findings: list[Finding] = []

    for doc in TIER1_DOCS:
        if not (REPO_ROOT / doc).exists():
            findings.append(Finding("error", "tier1-missing", f"Missing Tier-1 document: {doc}"))

    ledger = _load_ledger_text()
    entries = list(_iter_entries(ledger))
    all_routes = {route for e in entries for route in e.get("route_scope", [])}

    for route in sorted(REQUIRED_MISSION_ROUTES):
        if route not in all_routes:
            findings.append(Finding("error", "route-missing", f"Ledger missing mission runtime route: {route}"))

    # method specificity check for worker-run and runtime-task-materialization
    ambiguous_path_markers = [
        "/v1/missions/{mission_id}/worker-run-admission",
        "/v1/missions/{mission_id}/runtime-task-materialization",
    ]
    for marker in ambiguous_path_markers:
        if marker in all_routes:
            findings.append(Finding("error", "method-ambiguous", f"Method-agnostic route found for mixed-method path: {marker}"))

    for e in entries:
        entry_id = str(e.get("id", "<unknown>"))
        for field in OPERATOR_CUE_FIELDS:
            value = e.get(field)
            if value in (None, "", []):
                findings.append(Finding("warn", "operator-cue-missing", f"Entry {entry_id} missing operator cue field: {field}"))

    exit_code = 1 if strict and any(f.level == "error" for f in findings) else 0
    return findings, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="AJENDA contract drift sentinel")
    parser.add_argument("--strict", action="store_true", help="fail on error-level findings")
    parser.add_argument("--json", action="store_true", help="emit JSON findings")
    args = parser.parse_args()

    findings, exit_code = run_checks(strict=args.strict)
    if args.json:
        print(json.dumps([f.__dict__ for f in findings], indent=2))
    else:
        if not findings:
            print("OK: no drift findings")
        for f in findings:
            print(f"[{f.level.upper()}] {f.code}: {f.message}")
        if not args.strict and findings:
            print("WARN-MODE: findings reported; exiting 0")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
