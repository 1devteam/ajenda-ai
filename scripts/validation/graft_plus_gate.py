#!/usr/bin/env python3
"""Run Ajenda mission-contract and GRAFT+ architecture gates as one workflow."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = REPO_ROOT / "artifacts"


def _run(label: str, command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    return {
        "label": label,
        "status": "passed" if result.returncode == 0 else "failed",
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="HEAD^", help="Git ref used for impact comparison")
    parser.add_argument("--head-ref", default="HEAD", help="Git ref used for impact comparison")
    parser.add_argument("--output", type=Path, default=ARTIFACT_DIR / "graft-plus-gate.json")
    parser.add_argument("--skip-graph-tests", action="store_true", help="Skip the graph validator test suite")
    args = parser.parse_args()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []
    steps.append(_run("mission-contract-gate", [sys.executable, "scripts/validation/mission_contract_gate.py"]))
    steps.append(_run("build-canonical-graph", [sys.executable, "scripts/validation/build_dependency_graph.py"]))
    if not args.skip_graph_tests:
        steps.append(
            _run(
                "graph-validator-tests",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests/unit/validation/test_build_dependency_graph.py",
                    "tests/unit/validation/test_graph_impact_analysis.py",
                    "tests/unit/validation/test_graph_proof_selection.py",
                    "tests/unit/validation/test_graph_completeness_audit.py",
                    "tests/unit/validation/test_graph_architecture_decision.py",
                ],
            )
        )
    steps.append(
        _run(
            "impact-analysis",
            [
                sys.executable,
                "scripts/validation/graph_impact_analysis.py",
                "--base-ref",
                args.base_ref,
                "--head-ref",
                args.head_ref,
                "--json",
                "--output",
                "artifacts/graph-impact-report.json",
            ],
        )
    )
    steps.append(
        _run(
            "proof-selection",
            [
                sys.executable,
                "scripts/validation/graph_proof_selection.py",
                "--impact-report",
                "artifacts/graph-impact-report.json",
                "--json",
                "--output",
                "artifacts/graph-proof-manifest.json",
            ],
        )
    )
    steps.append(
        _run(
            "completeness-audit",
            [
                sys.executable,
                "scripts/validation/graph_completeness_audit.py",
                "--json",
                "--output",
                "artifacts/graph-completeness-report.json",
            ],
        )
    )
    steps.append(
        _run(
            "architecture-decision",
            [
                sys.executable,
                "scripts/validation/graph_architecture_decision.py",
                "--impact-report",
                "artifacts/graph-impact-report.json",
                "--proof-manifest",
                "artifacts/graph-proof-manifest.json",
                "--completeness-report",
                "artifacts/graph-completeness-report.json",
                "--json",
                "--output",
                "artifacts/graph-architecture-decision.json",
            ],
        )
    )
    report = {
        "schema_version": 1,
        "workflow": "mission-contract -> GRAFT+ graph -> impact -> proof -> completeness -> decision",
        "base_ref": args.base_ref,
        "head_ref": args.head_ref,
        "status": "passed" if all(step["status"] == "passed" for step in steps) else "failed",
        "steps": steps,
        "artifacts": [
            "artifacts/mission-contract-gate.json",
            "docs/architecture/dependency-graph.v1.json",
            "artifacts/graph-impact-report.json",
            "artifacts/graph-proof-manifest.json",
            "artifacts/graph-completeness-report.json",
            "artifacts/graph-architecture-decision.json",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"GRAFT+ gate: {report['status']} ({sum(step['status'] == 'passed' for step in steps)}/{len(steps)} steps passed)"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
