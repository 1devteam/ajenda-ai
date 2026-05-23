#!/usr/bin/env python3
"""Bundle 1.2 drift sentinel checker for ledger/route/doc parity."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
LEDGER = REPO_ROOT / "docs" / "contracts" / "authority-ledger.v1.yaml"
DOCS_FRESHNESS_POLICY = REPO_ROOT / "docs" / "policies" / "DOCS_FRESHNESS_POLICY.md"

ROUTE_FAMILY_RE = re.compile(r"^\s*- `/v1/([^`*]+)/\*`\s*$")
ROUTE_SCOPE_RE = re.compile(r"^\s*-\s+(/\S+)\s*$")
REVIEWED_DATE_RE = re.compile(r"\*\*Last reviewed:\*\*\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})")

TIER_1_DOCS = [
    "PROJECT_SPEC.md",
    "README.md",
    "docs/architecture/ADR_INDEX.md",
    "docs/validation/live-runtime-matrix.md",
    "docs/validation/live-runtime-proof-release-gate.md",
]


@dataclass
class DriftIssue:
    severity: str
    message: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_readme_route_families(readme_text: str) -> set[str]:
    return {m.group(1) for line in readme_text.splitlines() if (m := ROUTE_FAMILY_RE.match(line))}


def _parse_ledger_route_scopes(ledger_text: str) -> set[str]:
    scopes: set[str] = set()
    in_route_scope = False
    for raw_line in ledger_text.splitlines():
        line = raw_line.rstrip()
        if line.strip() == "route_scope: []":
            in_route_scope = False
            continue
        if line.strip() == "route_scope:":
            in_route_scope = True
            continue
        if in_route_scope:
            m = ROUTE_SCOPE_RE.match(line)
            if m:
                route = m.group(1)
                if route.startswith("/v1/"):
                    scopes.add(route)
                continue
            if line.startswith("    ") and line.strip() and not line.strip().startswith("-"):
                in_route_scope = False
            elif line.startswith("  - id:"):
                in_route_scope = False
    return scopes


def _route_families_from_scopes(scopes: set[str]) -> set[str]:
    families: set[str] = set()
    for scope in scopes:
        after_v1 = scope.split("/v1/", maxsplit=1)[1]
        head = after_v1.split("/", maxsplit=1)[0]
        if head:
            families.add(head)
    return families


def _parse_last_reviewed(path: Path) -> dt.date | None:
    content = _read(path)
    match = REVIEWED_DATE_RE.search(content)
    if not match:
        return None
    return dt.datetime.strptime(match.group(1), "%B %d, %Y").date()


def _check() -> list[DriftIssue]:
    issues: list[DriftIssue] = []

    for rel in TIER_1_DOCS:
        if not (REPO_ROOT / rel).exists():
            issues.append(DriftIssue("fail", f"Missing Tier-1 canonical doc: {rel}"))

    readme_text = _read(README)
    ledger_text = _read(LEDGER)

    readme_families = _parse_readme_route_families(readme_text)
    ledger_scopes = _parse_ledger_route_scopes(ledger_text)
    ledger_families = _route_families_from_scopes(ledger_scopes)

    missing_in_readme = sorted(ledger_families - readme_families)
    missing_in_ledger = sorted(readme_families - ledger_families)

    if missing_in_readme:
        issues.append(
            DriftIssue(
                "fail", f"README route inventory missing families from authority ledger: {', '.join(missing_in_readme)}"
            )
        )
    if missing_in_ledger:
        issues.append(
            DriftIssue(
                "fail", f"Authority ledger route_scope missing README route families: {', '.join(missing_in_ledger)}"
            )
        )

    reviewed = _parse_last_reviewed(DOCS_FRESHNESS_POLICY)
    if reviewed is None:
        issues.append(
            DriftIssue("warn", "DOCS_FRESHNESS_POLICY.md missing '**Last reviewed:** <Month DD, YYYY>' metadata.")
        )
    else:
        age_days = (dt.date.today() - reviewed).days
        if age_days > 30:
            issues.append(
                DriftIssue(
                    "warn",
                    f"DOCS_FRESHNESS_POLICY.md is stale by Tier-2 SLA ({age_days} days since {reviewed.isoformat()}).",
                )
            )

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drift sentinel checker for authority ledger, routes, and docs freshness metadata."
    )
    parser.add_argument("--strict", action="store_true", help="Treat warnings as failures.")
    args = parser.parse_args()

    issues = _check()
    fails = [i for i in issues if i.severity == "fail"]
    warns = [i for i in issues if i.severity == "warn"]

    for issue in fails:
        print(f"FAIL: {issue.message}")
    for issue in warns:
        print(f"WARN: {issue.message}")

    if not issues:
        print("PASS: drift sentinel checks passed.")
        return 0

    if fails:
        return 1
    if warns and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
