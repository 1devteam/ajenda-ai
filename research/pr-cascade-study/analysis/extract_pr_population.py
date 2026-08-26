#!/usr/bin/env python3
"""Extract the Ajenda pull-request population for the PR-cascade study.

This script intentionally separates deterministic repository observations from
semantic/causal adjudication. It can emit candidate explicit-reference edges,
but every such edge is marked ``unadjudicated``.

Usage example:

    GITHUB_TOKEN=... python research/pr-cascade-study/analysis/extract_pr_population.py \
        --repo 1devteam/ajenda-ai \
        --snapshot-max-pr 474 \
        --output-dir research/pr-cascade-study/data/generated

The extractor uses only Python's standard library so the census can be rerun in
minimal research environments.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

API_ROOT = "https://api.github.com"
USER_AGENT = "1DevTeam-PR-Cascade-Study/0.1"

# Deliberately conservative. Generic ``#123`` references are excluded because
# Dependabot/release-note bodies contain many unrelated upstream issue numbers.
PR_REF_PATTERNS = (
    re.compile(r"\bPR\s*#(\d+)\b", re.IGNORECASE),
    re.compile(r"\bpull\s+request\s*#(\d+)\b", re.IGNORECASE),
)

CENSUS_FIELDS = [
    "pr_number",
    "title",
    "state",
    "merged",
    "created_at",
    "updated_at",
    "closed_at",
    "merged_at",
    "author",
    "base_ref",
    "head_ref",
    "base_sha",
    "head_sha",
    "merge_sha",
    "commits",
    "changed_files",
    "additions",
    "deletions",
    "body_sha256",
    "referenced_prs",
    "population_role_raw",
    "signal_fix_title",
    "signal_hardening_title",
    "signal_revert",
    "signal_followup",
    "signal_supersession",
    "signal_root_cause_language",
    "signal_scope_or_non_goals",
    "signal_invariant_language",
    "signal_validation_or_proof",
    "signal_graph_language",
    "signal_review_feedback",
    "signal_failure_language",
    "signal_dependabot",
    "signal_research_only",
    "snapshot_max_pr",
    "extracted_at_utc",
]

EDGE_FIELDS = [
    "source_pr",
    "target_pr",
    "candidate_reason",
    "explicit_reference",
    "reference_direction_note",
    "relationship_class",
    "evidence_grade",
    "adjudication_status",
    "adjudication_notes",
]


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _contains(text: str, *needles: str) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles)


def _extract_pr_refs(text: str) -> list[int]:
    refs: set[int] = set()
    for pattern in PR_REF_PATTERNS:
        refs.update(int(match) for match in pattern.findall(text))
    return sorted(refs)


def _population_role(title: str, body: str, author: str) -> str:
    low_title = title.lower().strip()
    low_body = body.lower()
    low_author = author.lower()
    if "dependabot" in low_author or low_title.startswith("chore(deps") or low_title.startswith("chore(frontend-deps"):
        return "dependency_maintenance_candidate"
    if low_title.startswith("research:") or "research/pr-cascade-study" in low_body:
        return "research_candidate"
    if low_title.startswith("docs:") or low_title.startswith("chore(docs"):
        return "process_or_docs_candidate"
    return "product_candidate"


def _signals(title: str, body: str, author: str) -> dict[str, str]:
    full = f"{title}\n{body}"
    low_title = title.lower().strip()
    return {
        "signal_fix_title": _bool(low_title.startswith("fix") or " hotfix" in low_title),
        "signal_hardening_title": _bool(low_title.startswith("harden") or "harden" in low_title),
        "signal_revert": _bool(_contains(full, "revert", "reverts pr", "revert pr")),
        "signal_followup": _bool(_contains(full, "follow-up", "followup", "follow up", "addresses codex", "codex p1", "codex p2")),
        "signal_supersession": _bool(_contains(full, "supersede", "replacement for", "clean replacement", "replaces pr")),
        "signal_root_cause_language": _bool(_contains(full, "root cause", "root defect", "root defects")),
        "signal_scope_or_non_goals": _bool(_contains(full, "non-goal", "non goal", "scope discipline", "scope control", "not in this pr", "scope")),
        "signal_invariant_language": _bool(_contains(full, "invariant", "must remain", "must not", "fail closed", "fail-closed")),
        "signal_validation_or_proof": _bool(_contains(full, "validation", "proof", "tests", "tested")),
        "signal_graph_language": _bool(_contains(full, "canonical graph", "dependency graph", "graph-guided", "graph guided", "graph impact", "graph closure", "semantic finding")),
        "signal_review_feedback": _bool(_contains(full, "codex review", "codex p1", "codex p2", "review feedback", "late feedback")),
        "signal_failure_language": _bool(_contains(full, "failure", "failed", "regression", "defect", "gap", "bug")),
        "signal_dependabot": _bool("dependabot" in author.lower() or "dependabot" in full.lower()),
        "signal_research_only": _bool(low_title.startswith("research:") or "research-only" in full.lower() or "research instrumentation" in full.lower()),
    }


class GitHubClient:
    def __init__(self, token: str | None, *, pause_seconds: float = 0.0) -> None:
        self.token = token
        self.pause_seconds = pause_seconds

    def get_json(self, url: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub HTTP {exc.code} for {url}: {detail}") from exc
        if self.pause_seconds:
            time.sleep(self.pause_seconds)
        return payload


def _list_pr_numbers(client: GitHubClient, owner: str, repo: str, snapshot_max_pr: int) -> list[int]:
    numbers: list[int] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "state": "all",
                "per_page": 100,
                "page": page,
                "sort": "created",
                "direction": "asc",
            }
        )
        url = f"{API_ROOT}/repos/{owner}/{repo}/pulls?{query}"
        items = client.get_json(url)
        if not isinstance(items, list):
            raise RuntimeError(f"Unexpected PR-list response on page {page}")
        if not items:
            break
        for item in items:
            number = int(item["number"])
            if number <= snapshot_max_pr:
                numbers.append(number)
        if len(items) < 100:
            break
        if min(int(item["number"]) for item in items) > snapshot_max_pr:
            break
        page += 1
    return sorted(set(numbers))


def _get_pr(client: GitHubClient, owner: str, repo: str, number: int) -> dict[str, Any]:
    url = f"{API_ROOT}/repos/{owner}/{repo}/pulls/{number}"
    payload = client.get_json(url)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected PR response for #{number}")
    return payload


def _census_row(pr: dict[str, Any], *, snapshot_max_pr: int, extracted_at: str) -> dict[str, str]:
    number = int(pr["number"])
    title = str(pr.get("title") or "")
    body = str(pr.get("body") or "")
    author = str((pr.get("user") or {}).get("login") or "")
    refs = [ref for ref in _extract_pr_refs(body) if ref != number]
    row: dict[str, str] = {
        "pr_number": str(number),
        "title": title,
        "state": str(pr.get("state") or ""),
        "merged": _bool(pr.get("merged_at") is not None),
        "created_at": str(pr.get("created_at") or ""),
        "updated_at": str(pr.get("updated_at") or ""),
        "closed_at": str(pr.get("closed_at") or ""),
        "merged_at": str(pr.get("merged_at") or ""),
        "author": author,
        "base_ref": str((pr.get("base") or {}).get("ref") or ""),
        "head_ref": str((pr.get("head") or {}).get("ref") or ""),
        "base_sha": str((pr.get("base") or {}).get("sha") or ""),
        "head_sha": str((pr.get("head") or {}).get("sha") or ""),
        "merge_sha": str(pr.get("merge_commit_sha") or ""),
        "commits": str(pr.get("commits") if pr.get("commits") is not None else ""),
        "changed_files": str(pr.get("changed_files") if pr.get("changed_files") is not None else ""),
        "additions": str(pr.get("additions") if pr.get("additions") is not None else ""),
        "deletions": str(pr.get("deletions") if pr.get("deletions") is not None else ""),
        "body_sha256": _sha256(body),
        "referenced_prs": ";".join(str(ref) for ref in refs),
        "population_role_raw": _population_role(title, body, author),
        "snapshot_max_pr": str(snapshot_max_pr),
        "extracted_at_utc": extracted_at,
    }
    row.update(_signals(title, body, author))
    return row


def _candidate_edges(census_rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for row in census_rows:
        target = int(row["pr_number"])
        refs = [int(value) for value in row["referenced_prs"].split(";") if value]
        for ref in refs:
            note = "earlier PR referenced by later PR" if ref < target else "non-earlier PR reference; inspect direction"
            output.append(
                {
                    "source_pr": str(ref),
                    "target_pr": str(target),
                    "candidate_reason": "explicit PR reference in target PR body",
                    "explicit_reference": "true",
                    "reference_direction_note": note,
                    "relationship_class": "",
                    "evidence_grade": "",
                    "adjudication_status": "unadjudicated",
                    "adjudication_notes": "Explicit reference is not sufficient by itself to establish corrective causality.",
                }
            )
    return sorted(output, key=lambda row: (int(row["target_pr"]), int(row["source_pr"])))


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_manifest(path: Path, *, repo: str, snapshot_max_pr: int, numbers: list[int], extracted_at: str) -> None:
    expected = set(range(1, snapshot_max_pr + 1))
    observed = set(numbers)
    missing = sorted(expected - observed)
    manifest = {
        "repository": repo,
        "snapshot_max_pr": snapshot_max_pr,
        "extracted_at_utc": extracted_at,
        "observed_pr_count": len(numbers),
        "observed_min_pr": min(numbers) if numbers else None,
        "observed_max_pr": max(numbers) if numbers else None,
        "missing_numbers_within_1_to_snapshot": missing,
        "number_contiguity_is_not_assumed_to_equal_population_completeness": True,
        "source": "GitHub REST pull-request collection plus per-PR detail endpoint",
    }
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="1devteam/ajenda-ai", help="GitHub repository as owner/name")
    parser.add_argument("--snapshot-max-pr", type=int, required=True, help="Freeze extraction at this PR number")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("research/pr-cascade-study/data/generated"),
        help="Directory for generated census/edge files",
    )
    parser.add_argument("--pause-seconds", type=float, default=0.0, help="Optional delay between API requests")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        owner, repo_name = args.repo.split("/", 1)
    except ValueError as exc:
        raise SystemExit("--repo must be owner/name") from exc

    token = os.environ.get("GITHUB_TOKEN")
    client = GitHubClient(token, pause_seconds=max(args.pause_seconds, 0.0))
    extracted_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    numbers = _list_pr_numbers(client, owner, repo_name, args.snapshot_max_pr)
    rows: list[dict[str, str]] = []
    for index, number in enumerate(numbers, start=1):
        print(f"[{index}/{len(numbers)}] PR #{number}", file=sys.stderr)
        rows.append(
            _census_row(
                _get_pr(client, owner, repo_name, number),
                snapshot_max_pr=args.snapshot_max_pr,
                extracted_at=extracted_at,
            )
        )

    rows.sort(key=lambda row: int(row["pr_number"]))
    edges = _candidate_edges(rows)
    output_dir: Path = args.output_dir
    _write_csv(output_dir / "pr-census.csv", CENSUS_FIELDS, rows)
    _write_csv(output_dir / "candidate-explicit-reference-edges.csv", EDGE_FIELDS, edges)
    _write_manifest(
        output_dir / "extraction-manifest.json",
        repo=args.repo,
        snapshot_max_pr=args.snapshot_max_pr,
        numbers=numbers,
        extracted_at=extracted_at,
    )

    print(
        f"Wrote {len(rows)} PR census rows and {len(edges)} unadjudicated explicit-reference candidates to {output_dir}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
