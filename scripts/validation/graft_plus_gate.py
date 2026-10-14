#!/usr/bin/env python3
"""Run Ajenda mission-contract and GRAFT+ architecture gates as one workflow."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = REPO_ROOT / "artifacts"


_ACTIVE_REPORT: dict[str, Any] | None = None
_REPORT_PATH: Path | None = None
_ACTIVE_PROCESS: subprocess.Popen[str] | None = None


def _save_report() -> None:
    """Persist a usable checkpoint even if a later subprocess never returns."""
    if _ACTIVE_REPORT is None or _REPORT_PATH is None:
        return
    _REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _REPORT_PATH.with_name(_REPORT_PATH.name + ".tmp")
    temporary.write_text(json.dumps(_ACTIVE_REPORT, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(_REPORT_PATH)


def _run(label: str, command: list[str]) -> dict[str, Any]:
    global _ACTIVE_PROCESS
    assert _ACTIVE_REPORT is not None
    step: dict[str, Any] = {
        "label": label,
        "command": command,
        "status": "running",
        "returncode": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }
    _ACTIVE_REPORT["steps"].append(step)
    _ACTIVE_REPORT["status"] = "incomplete"
    _save_report()
    print(f"GRAFT+ starting {label}: {' '.join(command)}", flush=True)
    began = time.monotonic()
    try:
        # Separate files prevent a verbose test suite from filling pipe buffers.
        import tempfile

        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as out, tempfile.TemporaryFile(
            mode="w+t", encoding="utf-8"
        ) as err:
            _ACTIVE_PROCESS = subprocess.Popen(command, cwd=REPO_ROOT, text=True, stdout=out, stderr=err)
            try:
                while True:
                    try:
                        step["returncode"] = _ACTIVE_PROCESS.wait(timeout=30)
                        break
                    except subprocess.TimeoutExpired:
                        step["elapsed_seconds"] = round(time.monotonic() - began, 1)
                        _save_report()
                        print(f"GRAFT+ still running {label} ({step['elapsed_seconds']}s)", flush=True)
            finally:
                if _ACTIVE_PROCESS.poll() is None:
                    _ACTIVE_PROCESS.terminate()
                    try:
                        _ACTIVE_PROCESS.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        _ACTIVE_PROCESS.kill()
                        _ACTIVE_PROCESS.wait()
                _ACTIVE_PROCESS = None
            out.seek(0)
            err.seek(0)
            step["stdout_tail"] = out.read()[-4000:]
            step["stderr_tail"] = err.read()[-4000:]
        step["status"] = "passed" if step["returncode"] == 0 else "failed"
    except BaseException as exc:
        step["status"] = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
        step["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        step["elapsed_seconds"] = round(time.monotonic() - began, 1)
        _save_report()
        print(f"GRAFT+ {label}: {step['status']} (exit={step['returncode']})", flush=True)
        if step["status"] != "passed":
            if step["stderr_tail"]:
                print(step["stderr_tail"], file=sys.stderr, flush=True)
            if step["stdout_tail"]:
                print(step["stdout_tail"], file=sys.stderr, flush=True)
    return step


def _handle_signal(signum: int, _frame: Any) -> None:
    raise KeyboardInterrupt(f"signal {signum} received")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="HEAD^", help="Git ref used for impact comparison")
    parser.add_argument("--head-ref", default="HEAD", help="Git ref used for impact comparison")
    parser.add_argument("--output", type=Path, default=ARTIFACT_DIR / "graft-plus-gate.json")
    parser.add_argument("--skip-graph-tests", action="store_true", help="Skip the graph validator test suite")
    args = parser.parse_args()
    global _ACTIVE_REPORT, _REPORT_PATH
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    _REPORT_PATH = args.output
    steps: list[dict[str, Any]] = []
    _ACTIVE_REPORT = {
        "schema_version": 1,
        "workflow": "mission-contract -> GRAFT1st/lifecycle reconciliation -> GRAFT+ graph -> impact -> proof -> completeness -> decision",
        "base_ref": args.base_ref,
        "head_ref": args.head_ref,
        "status": "incomplete",
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
    _save_report()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    _run("mission-contract-gate", [sys.executable, "scripts/validation/mission_contract_gate.py"])
    
    _run(
        "graft1st-reconciliation-and-lifecycle",
        [sys.executable, "scripts/validation/graft_plus_graft1st_reconciliation_check.py"],
    )
    
    _run("build-canonical-graph", [sys.executable, "scripts/validation/build_dependency_graph.py"])
    
    _run(
        "graft-admission-and-drift-controls",
        [sys.executable, "scripts/validation/graft_drift_controls.py"],
    )
    
    if not args.skip_graph_tests:
        
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
                "tests/unit/validation/test_graph_runtime_impact.py",
                "tests/unit/validation/test_mission_verification_portfolio.py",
            ],
        )
        
    
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
    
    report = _ACTIVE_REPORT
    assert report is not None
    report["status"] = "passed" if all(step["status"] == "passed" for step in steps) else "failed"
    _save_report()
    print(
        f"GRAFT+ gate: {report['status']} ({sum(step['status'] == 'passed' for step in steps)}/{len(steps)} steps passed)"
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
