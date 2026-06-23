#!/usr/bin/env python3
"""Fail when backend/services imports from backend.api.routes (inverted layering)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICES_ROOT = REPO_ROOT / "backend" / "services"

IMPORT_RE = re.compile(
    r"^\s*(?:from\s+backend\.api\.routes(?:\.[a-z_]+)?\s+import|import\s+backend\.api\.routes(?:\.[a-z_]+)?)"
)

# Existing violations tracked for Phase 1b extraction. Remove entries as services are fixed.
ALLOWLIST: frozenset[str] = frozenset()


def _check() -> list[str]:
    violations: list[str] = []
    for path in sorted(SERVICES_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if not IMPORT_RE.search(text):
            continue
        if rel in ALLOWLIST:
            continue
        violations.append(rel)
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Service-to-route import layering check.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on allowlisted legacy imports too (post Phase 1b).",
    )
    args = parser.parse_args()

    violations: list[str] = []
    for path in sorted(SERVICES_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if not IMPORT_RE.search(text):
            continue
        if not args.strict and rel in ALLOWLIST:
            continue
        violations.append(rel)

    if violations:
        for rel in violations:
            print(f"FAIL: {rel} imports from backend.api.routes")
        if not args.strict:
            print(f"NOTE: {len(ALLOWLIST)} allowlisted legacy file(s) remain until Phase 1b completes.")
        return 1

    print("PASS: no disallowed service-to-route imports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
