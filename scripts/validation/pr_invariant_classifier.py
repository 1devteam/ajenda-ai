#!/usr/bin/env python3
"""Classify PR diffs against Ajenda architectural invariants.

This checker complements contract_drift_check.py.  The drift checker validates
repository-wide declared contracts; this checker starts from the files changed
by a PR/push and determines which architectural risk domains entered the blast
radius and which proof artifacts must change with them.

It intentionally fails only on deterministic evidence gaps.  Broader blast-
radius observations are reported as REVIEW items so the checker can be useful
without turning every architecture-sensitive edit into a false-positive gate.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_LEDGER = "docs/contracts/authority-ledger.v1.yaml"
PROVIDER_ROUTE_CONTRACT_TEST = "tests/contract/api/test_provider_credentials_routes.py"
RUNTIME_CREDENTIAL_REPOSITORY = "backend/services/credentials/sqlalchemy_repository.py"
PROVIDER_CREDENTIAL_ROUTE = "backend/api/routes/provider_credentials.py"
ACTION_REGISTRY = "backend/services/tools/action_registry.py"


@dataclass(frozen=True, slots=True)
class RiskProfile:
    id: str
    title: str
    patterns: tuple[str, ...]
    review: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str  # fail|review
    rule_id: str
    message: str


RISK_PROFILES: tuple[RiskProfile, ...] = (
    RiskProfile(
        id="tenant-isolation",
        title="Tenant isolation",
        patterns=(
            "backend/api/routes/*.py",
            "backend/app/dependencies/db.py",
            "backend/middleware/tenant_context.py",
            "backend/middleware/auth_context.py",
            "backend/repositories/*.py",
        ),
        review=(
            "tenant identity comes from validated request state",
            "tenant-facing DB access uses tenant-scoped session/RLS",
            "cross-tenant negative tests cover the changed surface",
        ),
    ),
    RiskProfile(
        id="runtime-authority",
        title="Runtime authority",
        patterns=(
            "backend/services/execution_coordinator.py",
            "backend/services/runtime_governor.py",
            "backend/services/worker_runtime_service.py",
            "backend/services/mission_runtime*.py",
            "backend/workers/*.py",
            "backend/workers/**/*.py",
            "backend/queue/*.py",
            "backend/runtime/*.py",
        ),
        review=(
            "queue admission still converges on canonical authority",
            "worker claim/start/run still converges on daemon runtime spine",
            "retry, side-effect approval, evidence, audit, and compensation semantics remain intact",
        ),
    ),
    RiskProfile(
        id="credential-boundary",
        title="Credential and connector authority",
        patterns=(
            PROVIDER_CREDENTIAL_ROUTE,
            "backend/services/credentials/*.py",
            "backend/services/credentials/**/*.py",
            "backend/domain/provider_runtime_credential.py",
            "backend/repositories/provider_runtime_credential_repository.py",
        ),
        review=(
            "connector OAuth remains separate from login identity",
            "OAuth state binds tenant, actor, credential, and provider",
            "stored secrets resolve to runtime access material only at invoke time",
            "raw secrets never enter task metadata or ordinary API responses",
        ),
    ),
    RiskProfile(
        id="external-egress",
        title="External provider egress",
        patterns=(
            "backend/services/network_egress.py",
            "backend/services/tools/*_provider.py",
            "backend/services/tools/*_actions.py",
            "backend/services/tools/provider_read_actions.py",
        ),
        review=(
            "external calls traverse NetworkEgressAuthority",
            "destination hosts are pinned to credential/provider policy",
            "side-effect class matches actual network behavior",
            "successful runtime work emits redacted evidence",
        ),
    ),
    RiskProfile(
        id="persistence",
        title="Persistence and migration",
        patterns=(
            "alembic/versions/*.py",
            "backend/domain/*.py",
            "backend/repositories/*.py",
        ),
        review=(
            "domain, repository, and migration contracts remain aligned",
            "upgrade/downgrade behavior is covered",
            "tenant ownership and indexes/constraints remain correct",
        ),
    ),
    RiskProfile(
        id="frontend-contract",
        title="Frontend/backend contract",
        patterns=(
            "frontend/src/api/client.ts",
            "frontend/src/App.tsx",
            "frontend/src/types.ts",
            "frontend/src/components/connections/*.tsx",
            "frontend/src/components/onboarding/*.tsx",
        ),
        review=(
            "frontend endpoints resolve to backend routes",
            "request/response types match backend contracts",
            "OAuth callbacks and session/error behavior remain fail-safe",
        ),
    ),
    RiskProfile(
        id="configuration",
        title="Configuration contract",
        patterns=(
            "backend/app/config.py",
            ".env.example",
            "deploy/compose/*.env*",
            "deploy/compose/*.yaml",
            "frontend/wrangler.jsonc",
        ),
        review=(
            "new settings have deployment/example parity",
            "production-required settings fail closed when absent",
            "secret-bearing configuration is not committed",
        ),
    ),
    RiskProfile(
        id="action-contract",
        title="Action/capability contract",
        patterns=(
            ACTION_REGISTRY,
            "backend/services/tools/schemas.py",
            "backend/services/tools/*_actions.py",
            "backend/services/abilities/*.py",
            "backend/services/mission_composition/*.py",
        ),
        review=(
            "action names are registered and stable",
            "input schema, side-effect class, credential requirement, and evidence agree",
            "declarative capability metadata does not become execution authority",
        ),
    ),
)


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def classify_risk_domains(changed_files: Iterable[str]) -> list[RiskProfile]:
    changed = tuple(changed_files)
    return [profile for profile in RISK_PROFILES if any(_matches(path, profile.patterns) for path in changed)]


def evaluate_proof_rules(*, changed_files: Iterable[str], added_files: Iterable[str]) -> list[Finding]:
    changed = set(changed_files)
    added = set(added_files)
    findings: list[Finding] = []

    new_oauth_connectors = sorted(
        path for path in added if fnmatch.fnmatch(path, "backend/services/credentials/*_oauth_connect.py")
    )
    if new_oauth_connectors:
        connector_names = ", ".join(Path(path).name.removesuffix("_oauth_connect.py") for path in new_oauth_connectors)
        if PROVIDER_CREDENTIAL_ROUTE not in changed:
            findings.append(
                Finding(
                    "fail",
                    "new-oauth-route-wiring",
                    f"New OAuth connector(s) [{connector_names}] require {PROVIDER_CREDENTIAL_ROUTE} wiring in the same change.",
                )
            )
        if AUTHORITY_LEDGER not in changed:
            findings.append(
                Finding(
                    "fail",
                    "new-oauth-authority-ledger",
                    f"New OAuth connector(s) [{connector_names}] require explicit authority-ledger coverage.",
                )
            )
        if PROVIDER_ROUTE_CONTRACT_TEST not in changed:
            findings.append(
                Finding(
                    "fail",
                    "new-oauth-route-proof",
                    f"New OAuth connector(s) [{connector_names}] require provider-credential HTTP contract coverage.",
                )
            )
        if RUNTIME_CREDENTIAL_REPOSITORY not in changed:
            findings.append(
                Finding(
                    "fail",
                    "new-oauth-runtime-resolution",
                    f"New OAuth connector(s) [{connector_names}] require runtime credential extraction/refresh wiring review in {RUNTIME_CREDENTIAL_REPOSITORY}.",
                )
            )
        if not any(path.startswith("tests/integration/credentials/") for path in changed):
            findings.append(
                Finding(
                    "review",
                    "new-oauth-integration-proof",
                    f"New OAuth connector(s) [{connector_names}] have no changed credential integration proof; document why live/runtime proof is deferred if unavailable.",
                )
            )

    changed_migrations = sorted(path for path in changed if fnmatch.fnmatch(path, "alembic/versions/*.py"))
    if changed_migrations and not any(
        path.startswith("tests/unit/db/") and "migration" in Path(path).name for path in changed
    ):
        findings.append(
            Finding(
                "fail",
                "migration-contract-proof",
                "Migration changes require at least one changed migration-contract test under tests/unit/db/.",
            )
        )

    new_action_modules = sorted(path for path in added if fnmatch.fnmatch(path, "backend/services/tools/*_actions.py"))
    if new_action_modules and ACTION_REGISTRY not in changed:
        findings.append(
            Finding(
                "fail",
                "new-action-registration",
                "New action modules require ActionRegistry wiring in the same change.",
            )
        )
    if new_action_modules and not any(path.startswith("tests/unit/tools/") for path in changed):
        findings.append(
            Finding(
                "fail",
                "new-action-proof",
                "New action modules require changed unit proof under tests/unit/tools/.",
            )
        )

    if PROVIDER_CREDENTIAL_ROUTE in changed and AUTHORITY_LEDGER not in changed:
        findings.append(
            Finding(
                "review",
                "credential-route-authority-review",
                "Provider credential routes changed without authority-ledger changes; verify no route authority or side-effect contract was added or expanded.",
            )
        )

    core_runtime = {
        "backend/services/execution_coordinator.py",
        "backend/services/worker_runtime_service.py",
        "backend/workers/worker_loop.py",
        "backend/workers/task_dispatcher.py",
    }
    if changed.intersection(core_runtime) and not any(
        path.startswith("tests/integration/runtime/") or path.startswith("tests/unit/workers/") for path in changed
    ):
        findings.append(
            Finding(
                "review",
                "runtime-spine-proof",
                "Core runtime authority changed without changed runtime/worker proof; verify existing tests cover the exact changed behavior or add targeted proof.",
            )
        )

    return findings


def _git_name_status(base_ref: str, head_ref: str) -> tuple[list[str], list[str]]:
    completed = subprocess.run(
        ["git", "diff", "--name-status", "--find-renames", base_ref, head_ref],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git diff failed")

    changed: list[str] = []
    added: list[str] = []
    for raw_line in completed.stdout.splitlines():
        parts = raw_line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        path = parts[-1]
        changed.append(path)
        if status.startswith("A") or status.startswith("R"):
            added.append(path)
    return sorted(set(changed)), sorted(set(added))


def _refs_from_github_event() -> tuple[str, str] | None:
    event_path = os.getenv("GITHUB_EVENT_PATH", "").strip()
    if not event_path:
        return None
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    pull_request = payload.get("pull_request")
    if isinstance(pull_request, dict):
        base = pull_request.get("base", {}).get("sha")
        head = pull_request.get("head", {}).get("sha")
        if isinstance(base, str) and isinstance(head, str) and base and head:
            return base, head

    before = payload.get("before")
    after = payload.get("after")
    if isinstance(before, str) and isinstance(after, str) and before.strip("0") and after.strip("0"):
        return before, after
    return None


def _discover_changes(base_ref: str | None, head_ref: str | None) -> tuple[list[str], list[str]]:
    if base_ref and head_ref:
        return _git_name_status(base_ref, head_ref)
    event_refs = _refs_from_github_event()
    if event_refs:
        return _git_name_status(*event_refs)
    return _git_name_status("HEAD^", "HEAD")


def _print_report(changed: list[str], added: list[str], *, as_json: bool) -> int:
    profiles = classify_risk_domains(changed)
    findings = evaluate_proof_rules(changed_files=changed, added_files=added)
    fails = [finding for finding in findings if finding.severity == "fail"]

    if as_json:
        print(
            json.dumps(
                {
                    "changed_files": changed,
                    "added_files": added,
                    "risk_domains": [
                        {"id": profile.id, "title": profile.title, "review": list(profile.review)}
                        for profile in profiles
                    ],
                    "findings": [
                        {"severity": finding.severity, "rule_id": finding.rule_id, "message": finding.message}
                        for finding in findings
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1 if fails else 0

    print(f"Changed files: {len(changed)} (added/renamed: {len(added)})")
    if profiles:
        for profile in profiles:
            print(f"RISK: {profile.id} — {profile.title}")
            for item in profile.review:
                print(f"  REVIEW: {item}")
    else:
        print("RISK: no architecture-sensitive domains detected")

    for finding in findings:
        print(f"{finding.severity.upper()}: {finding.rule_id}: {finding.message}")

    if fails:
        print(f"FAIL: PR invariant classifier found {len(fails)} deterministic evidence gap(s).")
        return 1
    print("PASS: PR invariant classifier found no deterministic evidence gaps.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify changed files against Ajenda architectural invariants.")
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--added-file", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if bool(args.base_ref) != bool(args.head_ref):
        parser.error("--base-ref and --head-ref must be supplied together")

    if args.changed_file:
        changed = sorted(set(args.changed_file))
        added = sorted(set(args.added_file))
    else:
        try:
            changed, added = _discover_changes(args.base_ref, args.head_ref)
        except RuntimeError as exc:
            print(f"FAIL: unable to determine changed files: {exc}")
            return 1

    return _print_report(changed, added, as_json=args.as_json)


if __name__ == "__main__":
    sys.exit(main())
