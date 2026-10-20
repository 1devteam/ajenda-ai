#!/usr/bin/env python3
"""Run isolated public-API mission proofs with trustworthy run linkage.

This is a proof harness, not an execution shortcut: every lane calls the
existing public onboarding and mission APIs through operator-mission-proof.py.
Fixture mode is deterministic and has no provider/CRM side effect. Live mode
is deliberately opt-in and requires an explicit instruction plus operator
authorization before it can use configured external read providers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The script is intentionally runnable directly from the repository root as
# documented below. Add its own validation directory before importing the
# sibling artifact helper; package-style imports remain available to tests.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from api_mission_proof_artifact import write_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]
OPERATOR_PROOF = REPO_ROOT / "deploy" / "scripts" / "operator-mission-proof.py"

FIXTURE_INSTRUCTIONS = (
    "Find three software companies in Austin using local fixture data only.",
    "Find three HVAC companies in Dallas using local fixture data only.",
    "Find three roofing companies in Austin using local fixture data only.",
    "Find three plumbing companies in Austin using local fixture data only.",
    "Find three advertising companies in Austin using local fixture data only.",
    "Find three electrical companies in Austin using local fixture data only.",
    "Find three landscaping companies in Austin using local fixture data only.",
    "Find three dental companies in Austin using local fixture data only.",
    "Find three recruiting companies in Austin using local fixture data only.",
    "Find three SaaS companies in Austin using local fixture data only.",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _current_commit() -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _json_summary(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("operator proof did not emit an object JSON summary")


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _proof_client_ip(*, run_id: str, lane: int) -> str:
    """Return a unique RFC 2544 benchmark address for one isolated proof lane."""

    digest = hashlib.sha256(f"{run_id}:{lane}".encode()).digest()
    return f"198.18.{digest[0] & 1}.{digest[1]}"


def _run_lane(
    *,
    run_dir: Path,
    run_id: str,
    lane: int,
    instruction: str,
    mode: str,
) -> dict[str, Any]:
    evidence_path = run_dir / f"lane-{lane:02d}-runtime-evidence.json"
    reconciliation_path = run_dir / f"lane-{lane:02d}-runtime-reconciliation.json"
    environment = dict(os.environ)
    environment.update(
        {
            "AJENDA_OPERATOR_PROOF_INSTRUCTION": instruction,
            "AJENDA_OPERATOR_PROOF_EXPECTED_PROSPECT_COUNT": "3",
            "AJENDA_OPERATOR_PROOF_RUNTIME_EVIDENCE_OUTPUT": str(evidence_path),
            "AJENDA_OPERATOR_PROOF_RUNTIME_RECONCILIATION_OUTPUT": str(reconciliation_path),
            # The local test harness receives a distinct RFC 2544 benchmark
            # address per run and signup lane. It exercises the ordinary
            # reverse-proxy client identity path without changing rate policy.
            "AJENDA_OPERATOR_PROOF_CLIENT_IP": _proof_client_ip(run_id=run_id, lane=lane),
        }
    )
    completed = subprocess.run(
        [sys.executable, str(OPERATOR_PROOF)],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    result: dict[str, Any] = {
        "lane": lane,
        "instruction_sha256": _digest(instruction),
        "mode": mode,
        "exit_code": completed.returncode,
        "status": "failed",
        # Never persist process output: it may contain service diagnostics.
        "stdout_sha256": _digest(completed.stdout),
        "stderr_sha256": _digest(completed.stderr),
    }
    if completed.returncode != 0:
        return result
    try:
        summary = _json_summary(completed.stdout)
        mission_id = summary.get("mission_id")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        reconciliation = json.loads(reconciliation_path.read_text(encoding="utf-8"))
        if not isinstance(mission_id, str) or not mission_id:
            raise ValueError("operator proof summary omitted mission_id")
        if not isinstance(evidence, dict) or evidence.get("mission_id") != mission_id:
            raise ValueError("runtime-evidence mission identity did not match operator-proof summary")
        if not isinstance(reconciliation, dict) or reconciliation.get("mission_id") != mission_id:
            raise ValueError("runtime-reconciliation mission identity did not match operator-proof summary")
        if not isinstance(reconciliation.get("provenance"), dict):
            raise ValueError("runtime-reconciliation export omitted provenance")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result["artifact_error"] = type(exc).__name__
        return result
    result.update(
        {
            "status": "passed",
            "mission_id": mission_id,
            "proposal_id": summary.get("proposal_id"),
            "runtime_evidence_path": evidence_path.name,
            "runtime_evidence_sha256": "sha256:" + hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            "runtime_reconciliation_path": reconciliation_path.name,
            "runtime_reconciliation_sha256": "sha256:" + hashlib.sha256(reconciliation_path.read_bytes()).hexdigest(),
        }
    )
    return result


def _live_instruction() -> str:
    if os.environ.get("AJENDA_API_PROOF_ALLOW_LIVE_PROVIDER") != "1":
        raise ValueError("live-provider proof requires AJENDA_API_PROOF_ALLOW_LIVE_PROVIDER=1")
    instruction = os.environ.get("AJENDA_API_PROOF_LIVE_INSTRUCTION", "").strip()
    if not instruction:
        raise ValueError("live-provider proof requires AJENDA_API_PROOF_LIVE_INSTRUCTION")
    if "fixture" in instruction.casefold():
        raise ValueError("live-provider proof instruction must not use fixture data")
    return instruction


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("fixture", "live-provider"), default="fixture")
    parser.add_argument("--count", type=int, default=None)
    args = parser.parse_args(argv)
    if args.count is not None and args.count < 1:
        parser.error("--count must be at least one")
    instructions = (
        FIXTURE_INSTRUCTIONS[: args.count or len(FIXTURE_INSTRUCTIONS)]
        if args.mode == "fixture"
        else (_live_instruction(),)
    )
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:12]}"
    run_dir = args.output_dir / run_id
    started_at = _utc_now()
    results = [
        _run_lane(run_dir=run_dir, run_id=run_id, lane=index, instruction=instruction, mode=args.mode)
        for index, instruction in enumerate(instructions, start=1)
    ]
    payload = {
        "schema_version": 1,
        "kind": "ajenda_api_mission_proof_suite",
        "run_id": run_id,
        "commit": _current_commit(),
        "mode": args.mode,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "result_count": len(results),
        "passed_count": sum(item["status"] == "passed" for item in results),
        "failed_count": sum(item["status"] != "passed" for item in results),
        "results": results,
    }
    artifact = write_manifest(run_dir / "manifest.json", payload)
    print(json.dumps({"artifact": str(run_dir / "manifest.json"), "integrity": artifact["integrity"]}, sort_keys=True))
    return 0 if payload["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
