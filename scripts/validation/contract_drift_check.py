#!/usr/bin/env python3
"""Bundle 1.2A authority drift sentinel (forward-build mode)."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
LEDGER = REPO_ROOT / "docs" / "contracts" / "authority-ledger.v1.yaml"
DOCS_FRESHNESS_POLICY = REPO_ROOT / "docs" / "policies" / "DOCS_FRESHNESS_POLICY.md"
API_ROUTER = REPO_ROOT / "backend" / "api" / "router.py"

SUPPORTED_AUTHORITY_CLASSES = {
    "declarative",
    "read_model",
    "governed_mutation",
    "runtime_authoritative",
}

ROUTE_FAMILY_RE = re.compile(r"^\s*- `/v1/([^`*]+)/\*`\s*$")
LAST_REVIEWED_RE = re.compile(r"\*\*Last reviewed:\*\*\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})")
INCLUDE_ROUTER_IMPORT_RE = re.compile(r"from backend\.api\.routes\.([a-z_]+) import router as")
INCLUDE_ROUTER_CALL_RE = re.compile(r"v1\.include_router\(([a-z_]+)_router\)")
ROUTER_PREFIX_RE = re.compile(r"APIRouter\([^\n)]*prefix\s*=\s*[\"'](/[^\"']*)[\"']")
ROUTE_DECORATOR_RE = re.compile(r"@router\.(?:get|post|put|patch|delete|options|head)\(\s*[\"'](/[^\"']*)[\"']")

REQUIRED_ENTRY_FIELDS = (
    "id",
    "area",
    "source_of_truth",
    "route_scope",
    "authority_class",
    "side_effect_class",
    "allowed_side_effects",
    "forbidden_side_effects",
    "required_proofs",
)


@dataclass
class DriftIssue:
    severity: str  # fail|warn
    message: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _safe_read(path: Path, *, missing_is_fail: bool = False, label: str = "file") -> tuple[str, list[DriftIssue]]:
    issues: list[DriftIssue] = []
    try:
        return _read(path), issues
    except FileNotFoundError:
        severity = "fail" if missing_is_fail else "warn"
        issues.append(DriftIssue(severity, f"Missing {label}: {path.relative_to(REPO_ROOT)}"))
    except OSError as exc:
        severity = "fail" if missing_is_fail else "warn"
        issues.append(DriftIssue(severity, f"Unable to read {label} {path.relative_to(REPO_ROOT)}: {exc}"))
    return "", issues


def _parse_readme_route_families(readme_text: str) -> set[str]:
    return {m.group(1) for line in readme_text.splitlines() if (m := ROUTE_FAMILY_RE.match(line))}


def _route_family_from_path(path: str) -> str | None:
    if path.startswith("/v1/"):
        candidate = path.split("/v1/", maxsplit=1)[1]
    elif path.startswith("/"):
        candidate = path.lstrip("/")
    else:
        return None
    family = candidate.split("/", maxsplit=1)[0]
    return family or None


def _route_families_from_scopes(scopes: set[str]) -> set[str]:
    return {family for scope in scopes if (family := _route_family_from_path(scope)) and scope.startswith("/v1/")}


def _parse_last_reviewed(text: str) -> dt.date | None:
    match = LAST_REVIEWED_RE.search(text)
    if not match:
        return None
    try:
        return dt.datetime.strptime(match.group(1), "%B %d, %Y").date()
    except ValueError:
        return None


def _load_ledger_entries(ledger_text: str) -> tuple[list[dict], list[DriftIssue]]:
    issues: list[DriftIssue] = []
    try:
        parsed = yaml.safe_load(ledger_text) if ledger_text.strip() else {}
    except yaml.YAMLError as exc:
        return [], [DriftIssue("fail", f"Malformed authority ledger YAML: {exc}")]

    if not isinstance(parsed, dict):
        return [], [DriftIssue("fail", "Invalid checker/parser state: ledger root must be a mapping.")]

    entries = parsed.get("authority_entries")
    if not isinstance(entries, list):
        return [], [DriftIssue("fail", "Invalid checker/parser state: authority_entries must be a list.")]

    normalized: list[dict] = []
    for idx, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            issues.append(DriftIssue("fail", f"Malformed ledger entry at index {idx}: expected mapping."))
            continue

        missing = [field for field in REQUIRED_ENTRY_FIELDS if field not in entry]
        if missing:
            issues.append(
                DriftIssue(
                    "fail",
                    f"Ledger entry '{entry.get('id', f'index-{idx}')}' missing required fields: {', '.join(missing)}",
                )
            )
            continue

        authority_class = entry.get("authority_class")
        if authority_class not in SUPPORTED_AUTHORITY_CLASSES:
            issues.append(
                DriftIssue(
                    "fail",
                    f"Ledger entry '{entry.get('id', f'index-{idx}')}' has unsupported authority_class: {authority_class}",
                )
            )
            continue

        normalized.append(entry)
    return normalized, issues


def _implemented_v1_route_families() -> tuple[set[str], list[DriftIssue]]:
    issues: list[DriftIssue] = []
    router_text, router_issues = _safe_read(API_ROUTER, missing_is_fail=True, label="router file")
    issues.extend(router_issues)
    if not router_text:
        return set(), issues

    module_names = {m.group(1) for m in INCLUDE_ROUTER_IMPORT_RE.finditer(router_text)}
    called_aliases = {m.group(1) for m in INCLUDE_ROUTER_CALL_RE.finditer(router_text)}

    if not called_aliases:
        issues.append(DriftIssue("fail", "Invalid checker/parser state: no v1 include_router calls found."))
        return set(), issues

    families: set[str] = set()
    for module in sorted(module_names.intersection(called_aliases)):
        route_file = REPO_ROOT / "backend" / "api" / "routes" / f"{module}.py"
        route_text, route_issues = _safe_read(route_file, missing_is_fail=False, label="route file")
        issues.extend(route_issues)
        if not route_text:
            continue

        module_families: set[str] = set()
        for m in ROUTER_PREFIX_RE.finditer(route_text):
            if (family := _route_family_from_path(m.group(1))) and family != "v1":
                module_families.add(family)

        if not module_families:
            for m in ROUTE_DECORATOR_RE.finditer(route_text):
                if (family := _route_family_from_path(m.group(1))) and family != "v1":
                    module_families.add(family)

        families.update(module_families)
    return families, issues


def _check(strict_baseline: bool = False) -> list[DriftIssue]:
    issues: list[DriftIssue] = []

    readme_text, readme_issues = _safe_read(README, missing_is_fail=True, label="canonical file")
    ledger_text, ledger_issues = _safe_read(LEDGER, missing_is_fail=True, label="canonical file")
    policy_text, policy_issues = _safe_read(DOCS_FRESHNESS_POLICY, missing_is_fail=False, label="policy file")
    issues.extend(readme_issues + ledger_issues + policy_issues)

    if not readme_text or not ledger_text:
        return issues

    readme_families = _parse_readme_route_families(readme_text)
    entries, entry_issues = _load_ledger_entries(ledger_text)
    issues.extend(entry_issues)

    ledger_scopes = {route for entry in entries for route in entry.get("route_scope", []) if isinstance(route, str)}
    ledger_families = _route_families_from_scopes(ledger_scopes)

    implemented_families, impl_issues = _implemented_v1_route_families()
    issues.extend(impl_issues)

    proof_paths = [proof for entry in entries for proof in entry.get("required_proofs", []) if isinstance(proof, str)]
    for proof in proof_paths:
        if not (REPO_ROOT / proof).exists():
            issues.append(DriftIssue("warn", f"Required proof path does not exist: {proof}"))

    for family in sorted(readme_families - ledger_families):
        issues.append(DriftIssue("warn", f"README route family missing from ledger: {family}"))
    for family in sorted(ledger_families - readme_families):
        issues.append(DriftIssue("warn", f"Ledger route family missing from README: {family}"))
    for family in sorted(implemented_families - (readme_families | ledger_families)):
        issues.append(DriftIssue("warn", f"Router-mounted family missing from README or ledger: {family}"))
    for family in sorted(readme_families - implemented_families):
        issues.append(DriftIssue("warn", f"README route family not mounted by implementation: {family}"))

    if "workforce" in (readme_families | ledger_families | implemented_families) and "workforces" in (
        readme_families | ledger_families | implemented_families
    ):
        issues.append(DriftIssue("warn", "Route family naming mismatch detected: workforce vs workforces."))

    if not policy_text.strip():
        issues.append(DriftIssue("warn", "DOCS_FRESHNESS_POLICY.md is missing Last reviewed metadata."))
    else:
        reviewed = _parse_last_reviewed(policy_text)
        if reviewed is None:
            if "Last reviewed" in policy_text:
                issues.append(DriftIssue("warn", "DOCS_FRESHNESS_POLICY.md has invalid Last reviewed date format."))
            else:
                issues.append(DriftIssue("warn", "DOCS_FRESHNESS_POLICY.md is missing Last reviewed metadata."))

    if strict_baseline:
        for issue in issues:
            if issue.severity == "warn":
                issue.severity = "fail"
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Authority drift sentinel checker.")
    parser.add_argument("--strict-baseline", action="store_true", help="Promote baseline warnings to failures.")
    args = parser.parse_args()

    issues = _check(strict_baseline=args.strict_baseline)
    fails = [i for i in issues if i.severity == "fail"]
    warns = [i for i in issues if i.severity == "warn"]

    for issue in fails:
        print(f"FAIL: {issue.message}")
    for issue in warns:
        print(f"WARN: {issue.message}")

    if not issues:
        print("PASS: authority drift sentinel checks passed.")
        return 0
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
