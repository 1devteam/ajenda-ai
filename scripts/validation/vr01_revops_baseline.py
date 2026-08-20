#!/usr/bin/env python3
"""Measure the non-executing Revenue Operations composition baseline.

This runner never confirms proposals, persists missions, queues tasks, or invokes tools.
It prints a stable JSON report suitable for archival by CI or an operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.services.mission_composition.proposal_store import clear_proposals_for_tests  # noqa: E402
from backend.services.mission_composition.service import MissionCompositionService  # noqa: E402

DEFAULT_CORPUS = REPO_ROOT / "tests/fixtures/vr01/revops-development.v1.json"
BASELINE_TENANT = "11111111-1111-1111-1111-111111111111"


def _revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _worktree_dirty() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def _strings(case: dict[str, Any], key: str) -> set[str]:
    raw = case.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise ValueError(f"{case.get('case_id', '<unknown>')}.{key} must be a string list")
    return set(raw)


def evaluate_case(service: MissionCompositionService, case: dict[str, Any]) -> dict[str, Any]:
    case_id = case.get("case_id")
    instruction = case.get("instruction")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be a non-empty string")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError(f"{case_id}.instruction must be a non-empty string")

    started = time.perf_counter()
    record = service.compose(tenant_id=BASELINE_TENANT, instruction=instruction)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    outcomes = set(record.intent.requested_outcomes)
    jobs = {item.job_key for item in record.job_assignments}
    actions = set(record.allowed_actions)
    required_outcomes = _strings(case, "required_outcomes")
    forbidden_outcomes = _strings(case, "forbidden_outcomes")
    required_jobs = _strings(case, "required_jobs")
    forbidden_actions = _strings(case, "forbidden_actions")
    checks = {
        "required_outcomes": required_outcomes <= outcomes,
        "forbidden_outcomes": not bool(forbidden_outcomes & outcomes),
        "required_jobs": required_jobs <= jobs,
        "forbidden_actions": not bool(forbidden_actions & actions),
        "status": record.proposal_status == case.get("expected_status"),
        "clarification": bool(record.clarifications) is bool(case.get("expected_clarification")),
    }
    return {
        "case_id": case_id,
        "scenario": case.get("scenario"),
        "passed": all(checks.values()),
        "checks": checks,
        "observed": {
            "proposal_status": record.proposal_status,
            "ready_to_start": record.ready_to_start,
            "coverage_score": record.intent.coverage_score,
            "requested_outcomes": sorted(outcomes),
            "jobs": sorted(jobs),
            "allowed_actions": sorted(actions),
            "clarification_fields": sorted(item.field for item in record.clarifications),
            "missing_connections": list(record.missing_connections),
            "unmatched_material_clause_count": len(record.intent.unmatched_material_clauses),
            "elapsed_ms": elapsed_ms,
        },
    }


def run(corpus_path: Path, *, expected_corpus_sha256: str | None = None) -> dict[str, Any]:
    corpus_bytes = corpus_path.read_bytes()
    corpus_sha256 = f"sha256:{hashlib.sha256(corpus_bytes).hexdigest()}"
    if expected_corpus_sha256 is not None and corpus_sha256 != expected_corpus_sha256:
        raise ValueError("corpus sha256 does not match sealed expectation")
    payload = json.loads(corpus_bytes)
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported corpus schema_version")
    corpus_kind = payload.get("corpus_kind")
    if corpus_kind not in {"development", "held_out"}:
        raise ValueError("corpus_kind must be development or held_out")
    sealed = payload.get("sealed")
    if not isinstance(sealed, bool):
        raise ValueError("corpus sealed must be a boolean")
    if corpus_kind == "held_out" and (not sealed or expected_corpus_sha256 is None):
        raise ValueError("held_out corpus requires sealed=true and an expected sha256")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("corpus cases must be a non-empty list")
    ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(ids) != len(cases) or len(ids) != len(set(ids)):
        raise ValueError("corpus case_id values must be present and unique")

    clear_proposals_for_tests()
    service = MissionCompositionService(db=None)
    results = [evaluate_case(service, case) for case in cases]
    passed = sum(1 for item in results if item["passed"])
    check_totals: dict[str, dict[str, int]] = {}
    for result in results:
        for name, ok in result["checks"].items():
            counts = check_totals.setdefault(name, {"passed": 0, "failed": 0})
            counts["passed" if ok else "failed"] += 1
    return {
        "schema_version": 1,
        "runner": "vr01_revops_baseline",
        "runner_version": "1",
        "corpus_id": payload.get("corpus_id"),
        "corpus_kind": corpus_kind,
        "corpus_sealed": sealed,
        "corpus_sha256": corpus_sha256,
        "corpus_path": (
            str(corpus_path.relative_to(REPO_ROOT))
            if corpus_path.is_relative_to(REPO_ROOT)
            else f"<external>/{corpus_path.name}"
        ),
        "code_revision": _revision(),
        "worktree_dirty": _worktree_dirty(),
        "authority": "evaluation_only",
        "grants_execution_authority": False,
        "summary": {"cases": len(results), "passed": passed, "failed": len(results) - passed},
        "check_totals": check_totals,
        "results": results,
        "not_measured": [
            "model_factuality",
            "human_draft_quality",
            "provider_latency_and_cost",
            "final_deliverable_completion",
            "external_effect_safety",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--expected-corpus-sha256")
    parser.add_argument("--require-all-pass", action="store_true")
    args = parser.parse_args()
    report = run(args.corpus.resolve(), expected_corpus_sha256=args.expected_corpus_sha256)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.require_all_pass and report["summary"]["failed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
