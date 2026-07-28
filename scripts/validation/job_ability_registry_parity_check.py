#!/usr/bin/env python3
"""Build-time integrity: job candidate actions ↔ registry ↔ ability manifests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
    from backend.services.mission_composition.contracts import CANONICAL_OUTCOMES
    from backend.services.mission_composition.job_catalog import BUSINESS_JOB_CATALOG
    from backend.services.tools.action_registry import get_default_action_registry

    registry = get_default_action_registry(rebuild=True)
    errors: list[str] = []
    routable_outcomes: set[str] = set()

    for job in BUSINESS_JOB_CATALOG:
        if job.maturity != "runtime_bound":
            continue
        for outcome in job.supported_outcomes:
            routable_outcomes.add(outcome)
        for action in job.candidate_actions:
            try:
                definition = registry.get(action)
            except Exception:
                errors.append(f"job {job.job_key}: action {action!r} missing from registry")
                continue
            canonical = definition.name
            if canonical not in ABILITY_MANIFESTS_BY_ACTION and action not in ABILITY_MANIFESTS_BY_ACTION:
                errors.append(
                    f"job {job.job_key}: action {action!r} (canonical {canonical!r}) missing ability manifest"
                )

    for outcome in CANONICAL_OUTCOMES:
        if outcome not in routable_outcomes:
            errors.append(f"canonical outcome {outcome!r} has no runtime_bound job")

    if errors:
        print("FAIL: job/ability/registry parity")
        for item in errors:
            print(f"  - {item}")
        return 1
    print("PASS: job candidate actions registered and manifested; outcomes job-bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
