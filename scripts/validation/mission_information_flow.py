#!/usr/bin/env python3
"""Map a committed Ajenda mission and locate differences against reviewed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.mission_composition.contracts import SemanticSnapshot
from backend.services.mission_runtime_evidence_projection import MissionRuntimeEvidenceProjection
from backend.services.runtime_reconciliation_contract import RuntimeReconciliationSnapshot, snapshot_digest
from scripts.validation.shadow_interpreter_trace import replay_interpreter

_TERMINAL = {"completed", "failed", "blocked", "cancelled", "archived", "dead_lettered"}
_MET = {"met", "satisfied", "complete", "completed"}


class ReviewedExpectations(BaseModel):
    """Stable outcomes and inputs reviewed for one exact instruction."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    instruction_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    requested_outcomes: list[str] | None = Field(default=None, max_length=50)
    target_scope: list[dict[str, str]] | None = Field(default=None, max_length=50)
    planned_actions: list[str] | None = Field(default=None, max_length=100)
    planned_inputs: dict[str, dict[str, JsonValue]] = Field(default_factory=dict, max_length=100)
    required_artifacts: list[str] = Field(default_factory=list, max_length=100)


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _objects(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: object) -> list[str] | None:
    return value if isinstance(value, list) and all(isinstance(item, str) for item in value) else None


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _summarize_value(value: Any, *, include_values: bool) -> Any:
    if include_values:
        return value
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"type": type(value).__name__, "sha256": _digest(encoded)}


def _runtime(snapshot: RuntimeReconciliationSnapshot) -> MissionRuntimeEvidenceProjection:
    if snapshot.provenance is None or snapshot.provenance.sha256 != snapshot_digest(snapshot):
        raise ValueError("runtime export is unsealed or its digest does not match its contents")
    if snapshot.runtime_evidence is None:
        raise ValueError("a version 2 reconciliation export with runtime evidence is required")
    return snapshot.runtime_evidence


def _scoped_events(runtime: MissionRuntimeEvidenceProjection) -> list[dict[str, Any]]:
    return [
        event
        for event in runtime.execution_events
        if event.get("tenant_id") == runtime.tenant_id and event.get("mission_id") == str(runtime.mission_id)
    ]


def _confirmed_instruction(events: list[dict[str, Any]]) -> tuple[str | None, str | None, list[str]]:
    receipts = [
        event
        for event in events
        if (event.get("category"), event.get("action")) == ("mission_composition", "confirmed")
        and event.get("runtime_evidence_integrity_verified") is True
    ]
    facts = [_object(_object(_object(event.get("payload")).get("runtime_evidence")).get("facts")) for event in receipts]
    fingerprints = {item["instruction_sha256"] for item in facts if isinstance(item.get("instruction_sha256"), str)}
    proposal_ids = {item["proposal_id"] for item in facts if isinstance(item.get("proposal_id"), str)}
    if len(fingerprints) > 1 or len(proposal_ids) > 1:
        raise ValueError("conflicting confirmation receipts prevent a unique mission join")
    return (
        next(iter(fingerprints), None),
        next(iter(proposal_ids), None),
        [event["event_id"] for event in receipts if isinstance(event.get("event_id"), str)],
    )


def _interpretation(events: list[dict[str, Any]], proposal_id: str | None) -> tuple[list[str] | None, list[str]]:
    if proposal_id is None:
        return None, []
    observed: list[list[str]] = []
    sources: list[str] = []
    for event in events:
        if (event.get("category"), event.get("action")) != ("mission_information", "composition_confirmed"):
            continue
        payload = _object(event.get("payload"))
        if payload.get("proposal_id") != proposal_id:
            continue
        outcomes = _strings(_object(payload.get("semantic_decisions")).get("requested_outcomes"))
        if outcomes is not None:
            observed.append(sorted(set(outcomes)))
            if isinstance(event.get("event_id"), str):
                sources.append(event["event_id"])
    if observed and all(item == observed[0] for item in observed):
        return observed[0], sources
    return None, sources


def _plan(runtime: MissionRuntimeEvidenceProjection) -> tuple[list[dict[str, Any]], bool]:
    nodes: list[dict[str, Any]] = []
    complete = bool(runtime.available_nodes)
    for node in runtime.available_nodes:
        invocation = _object(_object(node.get("input_contract")).get("tool_invocation"))
        key = node.get("node_key") or node.get("key")
        action = invocation.get("action")
        if not isinstance(key, str) or not isinstance(action, str):
            complete = False
            continue
        nodes.append(
            {
                "node_key": key,
                "action": action,
                "inputs": invocation.get("input"),
                "output_artifact": _object(node.get("output_contract")).get("artifact"),
                "selected_for_runtime": node.get("selected_for_runtime"),
            }
        )
    return nodes, complete


def _saved_semantics(
    mission_record: dict[str, Any] | None,
    *,
    runtime: MissionRuntimeEvidenceProjection,
    fingerprint: str | None,
) -> tuple[SemanticSnapshot, str, str | None] | None:
    if mission_record is None:
        return None
    if (
        mission_record.get("mission_id") != str(runtime.mission_id)
        or mission_record.get("tenant_id") != runtime.tenant_id
    ):
        raise ValueError("mission readback does not match the export mission and tenant")
    context = _object(_object(mission_record.get("intake")).get("context"))
    composition = _object(context.get("composition"))
    raw_semantic = composition.get("semantic_snapshot")
    if raw_semantic is None:
        return None
    semantic = SemanticSnapshot.model_validate(raw_semantic)
    saved_proposal = composition.get("proposal_id")
    saved_instruction = composition.get("instruction")
    if not isinstance(saved_proposal, str) or not saved_proposal or semantic.tenant_id != runtime.tenant_id:
        raise ValueError("saved semantic snapshot has invalid proposal or tenant scope")
    if (
        not isinstance(saved_instruction, str)
        or _digest(saved_instruction.encode("utf-8")) != semantic.instruction_sha256
    ):
        raise ValueError("saved semantic snapshot disagrees with its stored instruction")
    if fingerprint is not None and semantic.instruction_sha256 != fingerprint:
        raise ValueError("saved semantic snapshot disagrees with the confirmation instruction")
    prior = composition.get("revalidated_from_proposal_id")
    compile_parent = (
        prior
        if isinstance(prior, str)
        and prior == composition.get("reviewed_proposal_id")
        and composition.get("revision_reason") == "compile_revalidation"
        else None
    )
    return semantic, saved_proposal, compile_parent


def _baseline_expectations(
    snapshot: RuntimeReconciliationSnapshot, *, tenant_id: str, fingerprint: str
) -> ReviewedExpectations:
    runtime = _runtime(snapshot)
    if runtime.tenant_id != tenant_id:
        raise ValueError("baseline and observed export must belong to the same tenant")
    events = _scoped_events(runtime)
    baseline_fingerprint, proposal_id, _ = _confirmed_instruction(events)
    if baseline_fingerprint != fingerprint:
        raise ValueError("baseline and observed export must have the same confirmed instruction")
    if runtime.mission_status != "completed" or runtime.acceptance.get("status") not in _MET:
        raise ValueError("baseline must record a completed mission with satisfied acceptance")
    outcomes, _ = _interpretation(events, proposal_id)
    nodes, complete = _plan(runtime)
    queries: dict[str, dict[str, JsonValue]] = {}
    seen: set[str] = set()
    duplicates: set[str] = set()
    for node in nodes:
        key = node["node_key"]
        if key in seen:
            duplicates.add(key)
        seen.add(key)
        query = _object(node["inputs"]).get("query")
        if isinstance(query, str):
            queries[key] = {"query": query}
    return ReviewedExpectations(
        instruction_sha256=fingerprint,
        requested_outcomes=outcomes,
        planned_actions=sorted({node["action"] for node in nodes}) if complete else None,
        planned_inputs={key: value for key, value in queries.items() if key not in duplicates},
    )


def _task_map(runtime: MissionRuntimeEvidenceProjection, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_task: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        payload = _object(event.get("payload"))
        task_id = event.get("task_id")
        if not isinstance(task_id, str) and event.get("category") == "mission_information":
            task_id = payload.get("task_id")
        if isinstance(task_id, str):
            by_task.setdefault(task_id, []).append(event)
    flows = []
    for task in runtime.task_flows:
        task_id = task.get("task_id")
        task_events = by_task.get(task_id, []) if isinstance(task_id, str) else []
        observations = [
            {
                "event_id": event.get("event_id"),
                "category": event.get("category"),
                "action": event.get("action"),
                "integrity_verified_by_exporter": event.get("runtime_evidence_integrity_verified") is True,
            }
            for event in task_events
        ]
        flows.append(
            {
                "task_id": task_id,
                "node_key": task.get("node_key"),
                "status": task.get("status"),
                "queue_admitted": task.get("queue_admitted"),
                "lease_ids": _strings(task.get("lease_ids")),
                "bindings": [
                    {key: binding.get(key) for key in ("from_step", "output_path", "input_path")}
                    for binding in _objects(task.get("input_bindings"))
                ],
                "declared_artifact": _object(task.get("declared_output_contract")).get("artifact"),
                "observed_output_keys": _strings(task.get("observed_output_keys")),
                "output_shapes": {
                    key: {name: value[name] for name in ("shape", "count") if name in value}
                    for key, value in _object(task.get("output_summaries")).items()
                    if isinstance(value, dict)
                },
                "artifact_ids": _strings(task.get("artifact_ids")),
                "evidence_ids": _strings(task.get("evidence_ids")),
                "events": observations,
            }
        )
    return flows


def _recorded_flow(runtime: MissionRuntimeEvidenceProjection, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve attributed decisions and committed result projections without raw payloads."""
    by_event = {event["event_id"]: event for event in events if isinstance(event.get("event_id"), str)}
    fields = (
        "stage",
        "decision",
        "reason_code",
        "transformation_id",
        "selected_path",
        "rejected_paths",
        "field_lineage",
        "source_provenance",
        "event_id",
        "proposal_id",
        "task_id",
        "lease_id",
        "execution_path",
        "contract_version",
        "source",
        "producer",
        "integrity_trust_class",
    )
    flow = []
    for item in runtime.information_flow:
        if item.get("tenant_id", runtime.tenant_id) != runtime.tenant_id or item.get(
            "mission_id", str(runtime.mission_id)
        ) != str(runtime.mission_id):
            continue
        event_id = item.get("event_id")
        event = by_event.get(event_id) if isinstance(event_id, str) else None
        if event is None and (
            item.get("tenant_id") != runtime.tenant_id or item.get("mission_id") != str(runtime.mission_id)
        ):
            continue
        row = {key: item[key] for key in fields if key in item}
        if event is not None:
            payload = _object(event.get("payload"))
            for field in ("task_id", "proposal_id"):
                if field not in row:
                    reference = event.get(field) or payload.get(field)
                    if isinstance(reference, str):
                        row[field] = reference
        flow.append(row)
    return flow


def build_information_flow(
    snapshot: RuntimeReconciliationSnapshot,
    *,
    expectations: ReviewedExpectations | None = None,
    baseline: RuntimeReconciliationSnapshot | None = None,
    instruction: str | None = None,
    mission_record: dict[str, Any] | None = None,
    deliverable: dict[str, Any] | None = None,
    include_values: bool = False,
) -> dict[str, Any]:
    """Compare recorded boundaries, keeping replay and gaps distinct from receipts."""

    runtime = _runtime(snapshot)
    events = _scoped_events(runtime)
    fingerprint, proposal_id, confirmation_ids = _confirmed_instruction(events)
    saved = _saved_semantics(mission_record, runtime=runtime, fingerprint=fingerprint)
    semantic = saved[0] if saved else None
    saved_proposal = saved[1] if saved else None
    compile_parent = saved[2] if saved else None
    proposal_link_status = "unobserved"
    if proposal_id is not None and saved_proposal is not None:
        if proposal_id == saved_proposal:
            proposal_link_status = "matched"
        elif proposal_id == compile_parent:
            proposal_link_status = "compile_revalidation"
        else:
            proposal_link_status = "different_proposals"
    instruction_source = "confirmation_receipt" if fingerprint is not None else None
    if saved is not None:
        if fingerprint is None:
            fingerprint = saved[0].instruction_sha256
            instruction_source = "saved_mission_semantic_snapshot"
    if expectations is not None and baseline is not None:
        raise ValueError("use either reviewed expectations or a baseline export")
    if baseline is not None:
        if fingerprint is None:
            raise ValueError("recorded instruction fingerprint is required for baseline comparison")
        expectations = _baseline_expectations(baseline, tenant_id=runtime.tenant_id, fingerprint=fingerprint)
    if expectations is not None and expectations.instruction_sha256 != fingerprint:
        raise ValueError("reviewed expectations do not match the confirmed instruction")

    shadow = None
    if instruction is not None:
        if _digest(instruction.encode("utf-8")) != fingerprint:
            raise ValueError("replay instruction does not match the confirmed instruction")
        shadow = replay_interpreter(instruction).report()
    observed_outcomes, interpretation_ids = _interpretation(events, proposal_id or saved_proposal)
    outcomes = sorted(set(semantic.requested_outcomes)) if semantic is not None else observed_outcomes
    semantic_path = "mission.intake.context.composition.semantic_snapshot"
    target_scope = (
        [
            {key: item[key] for key in ("type", "industry", "location") if isinstance(item.get(key), str)}
            for item in semantic.target_entities
        ]
        if semantic is not None
        else None
    )
    nodes, complete_plan = _plan(runtime)
    planned_actions = sorted({node["action"] for node in nodes}) if complete_plan else None
    if deliverable is not None and deliverable.get("mission_id") != str(runtime.mission_id):
        raise ValueError("deliverable readback does not belong to the exported mission")
    if deliverable is not None and deliverable.get("tenant_id", runtime.tenant_id) != runtime.tenant_id:
        raise ValueError("deliverable readback tenant does not match the export")
    artifact_payloads = deliverable.get("artifacts") if deliverable is not None else None
    artifact_keys = sorted(artifact_payloads) if isinstance(artifact_payloads, dict) else None

    checks: list[dict[str, Any]] = []

    def compare(stage: str, field: str, expected: Any, observed: Any, sources: list[str]) -> None:
        checks.append(
            {
                "stage": stage,
                "field": field,
                "status": "unobserved" if observed is None else "matched" if observed == expected else "mismatch",
                "expected": expected,
                "observed": observed,
                "sources": sources,
            }
        )

    if expectations is not None:
        if expectations.target_scope is not None:
            compare(
                "interpretation",
                "target_scope",
                _summarize_value(expectations.target_scope, include_values=include_values),
                _summarize_value(target_scope, include_values=include_values) if target_scope is not None else None,
                [f"{semantic_path}.target_entities"] if target_scope is not None else [],
            )
        if expectations.requested_outcomes is not None:
            compare(
                "interpretation",
                "requested_outcomes",
                sorted(set(expectations.requested_outcomes)),
                outcomes,
                [f"{semantic_path}.requested_outcomes"] if semantic is not None else interpretation_ids,
            )
        if expectations.planned_actions is not None:
            compare(
                "plan",
                "actions",
                sorted(set(expectations.planned_actions)),
                planned_actions,
                ["runtime_evidence.available_nodes"],
            )
        for key, fields in sorted(expectations.planned_inputs.items()):
            matches = [node["inputs"] for node in nodes if node["node_key"] == key]
            inputs = matches[0] if len(matches) == 1 else None
            for field, expected in sorted(fields.items()):
                if not isinstance(inputs, dict):
                    observed = None
                elif field not in inputs:
                    observed = {"missing": True}
                else:
                    observed = {"value": _summarize_value(inputs[field], include_values=include_values)}
                compare(
                    "plan",
                    f"{key}.{field}",
                    {"value": _summarize_value(expected, include_values=include_values)},
                    observed,
                    ["runtime_evidence.available_nodes"],
                )
        for key in sorted(set(expectations.required_artifacts)):
            compare(
                "deliverable",
                key,
                True,
                key in artifact_keys if artifact_keys is not None and runtime.mission_status in _TERMINAL else None,
                ["mission_deliverable.artifacts"] if artifact_keys is not None else [],
            )

    for node in nodes:
        inputs = node.pop("inputs")
        if isinstance(inputs, dict):
            node["input_fields"] = sorted(inputs)

    first = next((item for item in checks if item["status"] == "mismatch"), None)
    earlier_unobserved = []
    for item in checks:
        if item is first:
            break
        if item["status"] == "unobserved":
            earlier_unobserved.append(item["field"])
    return {
        "schema_version": 1,
        "read_only": True,
        "grants_execution_authority": False,
        "mission_id": str(runtime.mission_id),
        "source_export_sha256": snapshot.provenance.sha256 if snapshot.provenance else None,
        "export_source_authenticity_verified": False,
        "comparison_source": (
            f"baseline:{baseline.mission_id}"
            if baseline is not None
            else "reviewed_expectations"
            if expectations is not None
            else None
        ),
        "instruction_sha256": fingerprint,
        "instruction_source": instruction_source,
        "confirmation_event_ids": confirmation_ids,
        "interpretation": {
            "requested_outcomes": outcomes,
            "semantic_snapshot_id": semantic.snapshot_id if semantic is not None else None,
            "confirmation_proposal_id": proposal_id,
            "saved_mission_proposal_id": saved_proposal,
            "saved_compile_parent_proposal_id": compile_parent,
            "proposal_link_status": proposal_link_status,
            "observation_disagrees_with_snapshot": (
                outcomes != observed_outcomes if semantic is not None and observed_outcomes is not None else None
            ),
            "target_scope": _summarize_value(target_scope, include_values=include_values)
            if target_scope is not None
            else None,
            "event_ids": interpretation_ids,
        },
        "compiled_plan": nodes,
        "tasks": _task_map(runtime, events),
        "recorded_information_flow": _recorded_flow(runtime, events),
        "information_coverage": runtime.information_coverage,
        "deliverable": {
            "artifact_keys": artifact_keys,
            "complete": _object(_object(deliverable).get("completion")).get("complete"),
        },
        "acceptance": {"mission_status": runtime.mission_status, "status": runtime.acceptance.get("status")},
        "graft": {
            "first_recorded_divergence": runtime.first_divergence,
            "missing_evidence": runtime.missing_evidence,
            "historical_unknown": runtime.historical_unknown,
            "contradictions": runtime.contradictions,
        },
        "checks": checks,
        "first_supported_mismatch": first,
        "earlier_unobserved_checks": earlier_unobserved,
        "shadow_replay": shadow,
    }


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected a JSON object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path, help="JSON from the mission runtime-reconciliation-export route")
    reference = parser.add_mutually_exclusive_group()
    reference.add_argument("--expectations", type=Path, help="Reviewed check definitions for the confirmed instruction")
    reference.add_argument("--baseline", type=Path, help="Prior passing export with the same tenant and instruction")
    parser.add_argument("--instruction-file", type=Path, help="Replay the exact original instruction with local Shadow")
    parser.add_argument("--mission-record", type=Path, help="JSON from the same mission's GET /v1/missions/{id} route")
    parser.add_argument("--deliverable", type=Path, help="JSON from the same mission's deliverable route")
    parser.add_argument(
        "--include-values", action="store_true", help="Include reviewed field values in the local report"
    )
    args = parser.parse_args()
    try:
        report = build_information_flow(
            RuntimeReconciliationSnapshot.model_validate(_read_object(args.snapshot)),
            expectations=ReviewedExpectations.model_validate(_read_object(args.expectations))
            if args.expectations
            else None,
            baseline=RuntimeReconciliationSnapshot.model_validate(_read_object(args.baseline))
            if args.baseline
            else None,
            instruction=args.instruction_file.read_bytes().decode("utf-8") if args.instruction_file else None,
            mission_record=_read_object(args.mission_record) if args.mission_record else None,
            deliverable=_read_object(args.deliverable) if args.deliverable else None,
            include_values=args.include_values,
        )
    except (OSError, ValueError, ValidationError) as exc:
        # An invalid model may embed its input value in exception text.
        parser.exit(
            2,
            f"Cannot map mission information flow: {type(exc).__name__}\n"
            if isinstance(exc, ValidationError)
            else f"Cannot map mission information flow: {exc}\n",
        )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
