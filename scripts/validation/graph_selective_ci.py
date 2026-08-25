#!/usr/bin/env python3
"""Execute graph-selected proof in CI shadow mode.

The shadow runner never suppresses the repository's existing full PR gate. It
validates the proof manifest, executes graph-selected focused pytest paths, and
reports whether broad/full-suite fallback would still be required.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPPORTED_PROOF_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})
ALLOWED_REQUIRED_GATES = frozenset(
    {
        "frontend-build-audit",
        "integration-tests",
        "lint-type-check",
        "migration-round-trip",
        "unit-tests",
    }
)
ALLOWED_REVIEW_GATES = frozenset({"live-runtime-proof"})


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"unable to read proof manifest: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"proof manifest is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("proof manifest root must be a JSON object")
    if str(payload.get("schema_version")) not in SUPPORTED_PROOF_SCHEMA_VERSIONS:
        raise RuntimeError("unsupported proof manifest schema_version")
    return payload


def _string_list(manifest: dict[str, Any], field: str) -> list[str]:
    value = manifest.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise RuntimeError(f"proof manifest field {field!r} must be a list of non-empty strings")
    return sorted(set(value))


def _validate_tests(test_paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw_path in test_paths:
        path = Path(raw_path)
        if path.is_absolute() or ".." in path.parts:
            raise RuntimeError(f"unsafe test path in proof manifest: {raw_path}")
        if not raw_path.startswith("tests/") or not raw_path.endswith(".py"):
            raise RuntimeError(f"proof test path must be a Python test under tests/: {raw_path}")
        resolved = (REPO_ROOT / path).resolve()
        if REPO_ROOT not in resolved.parents:
            raise RuntimeError(f"test path escapes repository root: {raw_path}")
        if not resolved.is_file():
            raise RuntimeError(f"proof test path does not exist: {raw_path}")
        normalized.append(path.as_posix())
    return sorted(set(normalized))


def build_shadow_plan(manifest: dict[str, Any]) -> dict[str, Any]:
    tests = _validate_tests(_string_list(manifest, "required_tests"))
    required_gates = _string_list(manifest, "required_gates")
    review_gates = _string_list(manifest, "review_gates")
    manual_review = _string_list(manifest, "manual_review")

    unknown_required = sorted(set(required_gates) - ALLOWED_REQUIRED_GATES)
    unknown_review = sorted(set(review_gates) - ALLOWED_REVIEW_GATES)
    if unknown_required:
        raise RuntimeError(f"unknown required gate(s): {', '.join(unknown_required)}")
    if unknown_review:
        raise RuntimeError(f"unknown review gate(s): {', '.join(unknown_review)}")

    unit_tests = sorted(path for path in tests if not path.startswith("tests/integration/"))
    integration_tests = sorted(path for path in tests if path.startswith("tests/integration/"))
    fallback_reasons: list[str] = []
    if manual_review:
        fallback_reasons.append("manual review is required")
    if "migration-round-trip" in required_gates:
        fallback_reasons.append("migration safety is required")
    if "frontend-build-audit" in required_gates:
        fallback_reasons.append("frontend build/audit is required")
    if "lint-type-check" in required_gates:
        fallback_reasons.append("static analysis is required")
    if review_gates:
        fallback_reasons.append("review-only runtime proof is requested")

    return {
        "schema_version": "1.1",
        "source_manifest_schema_version": str(manifest.get("schema_version")),
        "unit_tests": unit_tests,
        "integration_tests": integration_tests,
        "required_gates": required_gates,
        "review_gates": review_gates,
        "manual_review": manual_review,
        "full_suite_fallback": bool(fallback_reasons),
        "fallback_reasons": fallback_reasons,
    }


def _run_pytest(paths: list[str], *, integration: bool, dry_run: bool) -> int:
    if not paths:
        return 0
    marker = "integration" if integration else "not integration"
    command = [sys.executable, "-m", "pytest", *paths, "-v", "--tb=short", "-m", marker]
    if integration:
        command.append("--timeout=60")
    print("RUN:", " ".join(command))
    if dry_run:
        return 0
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute graph-selected proof in shadow mode.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        manifest = _load_manifest(Path(args.manifest))
        plan = build_shadow_plan(manifest)
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1

    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")

    unit_result = _run_pytest(plan["unit_tests"], integration=False, dry_run=args.dry_run)
    if unit_result != 0:
        return unit_result
    integration_result = _run_pytest(plan["integration_tests"], integration=True, dry_run=args.dry_run)
    if integration_result != 0:
        return integration_result

    if plan["full_suite_fallback"]:
        print("SHADOW: full-suite fallback would remain required:")
        for reason in plan["fallback_reasons"]:
            print(f"  - {reason}")
    else:
        print("SHADOW: focused graph-selected proof completed without a fallback signal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
