#!/usr/bin/env python3
"""Evaluate one durable mission execution slice against GRAFT integrity rules."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

TERMINAL_TASK_STATES = frozenset({"blocked", "cancelled", "completed", "dead_lettered", "failed"})
ACTIVE_MISSION_STATES = frozenset({"approved", "queued", "running"})
REPORT_DELIVERABLE_RE = re.compile(
    r"\b(?:comparison\s+table|compare\b|report\b|highlight\b|market\s+opportunit(?:y|ies)|evidence\s+gap)",
    re.IGNORECASE,
)
REPORT_ARTIFACTS = frozenset({"comparison_report", "mission_report", "research_report"})
GOOGLE_CONTACTS_REQUEST_RE = re.compile(
    r"\bgoogle\s+contacts?\b|\b(?:check|read|list|show|fetch|get)\s+(?:my\s+|the\s+)?contacts?\b",
    re.IGNORECASE,
)


def _finding(code: str, message: str, *, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": "blocking", "message": message, "evidence": evidence}


def _task_nodes(context: dict[str, Any]) -> list[dict[str, Any]]:
    graph = context.get("task_graph") or {}
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    return [node for node in nodes or [] if isinstance(node, dict)]


def _research_outputs(task_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for task in task_results:
        candidates = [task.get("output")]
        handler = task.get("handler_result")
        if isinstance(handler, dict):
            candidates.append(handler.get("output"))
        metadata = task.get("metadata_json")
        if isinstance(metadata, dict):
            metadata_handler = metadata.get("handler_result")
            if isinstance(metadata_handler, dict):
                candidates.append(metadata_handler.get("output"))
        outputs.extend(item for item in candidates if isinstance(item, dict))
    return outputs


def evaluate_mission_instance(context: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic, non-executing findings for one mission snapshot."""

    instruction = str(context.get("instruction") or "")
    objective = str(context.get("objective") or "")
    mission_status = str(context.get("mission_status") or "")
    nodes = _task_nodes(context)
    task_results = [item for item in context.get("task_results") or [] if isinstance(item, dict)]
    findings: list[dict[str, Any]] = []

    for output in _research_outputs(task_results):
        candidates = output.get("prospect_candidates")
        public_rows = [
            row for row in candidates or [] if isinstance(row, dict) and row.get("source") == "public_search"
        ]
        unverified_rows = [
            row for row in public_rows if row.get("real") is not True or row.get("identity_status") != "verified"
        ]
        if unverified_rows:
            findings.append(
                _finding(
                    "research.public_identity_unverified",
                    "Public search rows reached the compiled mission result without verified company identity.",
                    evidence={"row_count": len(unverified_rows)},
                )
            )
        elif output.get("include_public_search") and output.get("web_result_count", 0) and not public_rows:
            findings.append(
                _finding(
                    "research.public_identity_unresolved",
                    "Public search returned results but produced no verified compiled prospect candidates.",
                    evidence={"web_result_count": output.get("web_result_count")},
                )
            )

    quoted_lines = [line for line in instruction.splitlines() if line.lstrip().startswith(">")]
    if quoted_lines:
        findings.append(
            _finding(
                "mission_input.markdown_quote_leaked",
                "Markdown quote prefixes reached the durable mission instruction.",
                evidence={"quoted_line_count": len(quoted_lines)},
            )
        )

    if objective.endswith("...") and len(instruction.strip()) > len(objective):
        findings.append(
            _finding(
                "mission_input.objective_truncated",
                "The durable objective is a lossy truncation of the source instruction.",
                evidence={"instruction_length": len(instruction.strip()), "objective_length": len(objective)},
            )
        )

    google_contact_nodes = [
        str(node.get("key") or node.get("node_key") or "")
        for node in nodes
        if str((node.get("metadata") or {}).get("job_key") or "") == "ops.google_contacts_read"
    ]
    if google_contact_nodes and GOOGLE_CONTACTS_REQUEST_RE.search(instruction) is None:
        findings.append(
            _finding(
                "mission_selection.unsupported_google_contacts",
                "Google Contacts was selected without an explicit positive contacts-read request.",
                evidence={"node_keys": google_contact_nodes},
            )
        )

    requested_report = REPORT_DELIVERABLE_RE.search(instruction) is not None
    produced_artifacts = {str((node.get("output_contract") or {}).get("artifact") or "") for node in nodes}
    if requested_report and not (produced_artifacts & REPORT_ARTIFACTS):
        findings.append(
            _finding(
                "mission_deliverable.report_not_materialized",
                "The mission requests a synthesized report but no graph node produces a report artifact.",
                evidence={"produced_artifacts": sorted(value for value in produced_artifacts if value)},
            )
        )

    credential_failures = [
        {
            "task_id": str(item.get("task_id") or ""),
            "failure": str(item.get("failure") or ""),
        }
        for item in task_results
        if "decrypt runtime credential" in str(item.get("failure") or "").lower()
    ]
    if credential_failures:
        findings.append(
            _finding(
                "mission_credential.runtime_secret_mismatch",
                "At least one selected credential cannot be decrypted by the active runtime key.",
                evidence={"tasks": credential_failures},
            )
        )

    states = [str(item.get("status") or "") for item in task_results]
    if states and all(state in TERMINAL_TASK_STATES for state in states) and mission_status in ACTIVE_MISSION_STATES:
        findings.append(
            _finding(
                "mission_state.terminal_tasks_active_mission",
                "All materialized tasks are terminal while the mission remains active.",
                evidence={"mission_status": mission_status, "task_states": states},
            )
        )

    rendered_context = json.dumps(context, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "1.0",
        "scope": "graft-mission-instance-integrity",
        "context_sha256": hashlib.sha256(rendered_context.encode()).hexdigest(),
        "status": "blocked" if findings else "clear",
        "findings": findings,
        "metrics": {"blocking_count": len(findings), "node_count": len(nodes), "task_result_count": len(task_results)},
        "policy": {"enforcement": "diagnostic", "executes_work": False, "mutates_runtime": False},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    context = json.loads(args.context.read_text(encoding="utf-8"))
    if not isinstance(context, dict):
        raise ValueError("context JSON must contain one object")
    report = evaluate_mission_instance(context)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "GRAFT mission-instance integrity: "
        f"{report['status']}; {report['metrics']['blocking_count']} blocking finding(s)"
    )
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
