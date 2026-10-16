"""Independent read-side consumers for versioned audit-ledger runtime facts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from backend.domain.audit_event import AuditEvent
from backend.services.runtime_evidence_ledger import (
    RUNTIME_EVIDENCE_PAYLOAD_KEY,
    RuntimeEvidenceEnvelope,
    RuntimeEvidenceLedger,
)


@dataclass(frozen=True, slots=True)
class RuntimeEvidenceConsumerResult:
    envelopes: tuple[RuntimeEvidenceEnvelope, ...]
    findings: tuple[dict[str, str], ...]


def consume_runtime_security_evidence(events: Iterable[AuditEvent]) -> RuntimeEvidenceConsumerResult:
    """Verify ledger envelope integrity and binding without changing runtime state."""

    envelopes: list[RuntimeEvidenceEnvelope] = []
    findings: list[dict[str, str]] = []
    for event in events:
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        has_runtime_evidence = RUNTIME_EVIDENCE_PAYLOAD_KEY in payload
        envelope = RuntimeEvidenceLedger.read_envelope(event)
        if envelope is None:
            if has_runtime_evidence:
                findings.append(
                    {
                        "category": "runtime_evidence_integrity",
                        "code": f"audit:{event.id}:invalid_envelope",
                        "severity": "error",
                    }
                )
            continue
        envelopes.append(envelope)
    return RuntimeEvidenceConsumerResult(envelopes=tuple(envelopes), findings=tuple(findings))


def consume_intelligence_flow_evidence(events: Iterable[AuditEvent]) -> RuntimeEvidenceConsumerResult:
    """Expose first missing or semantically divergent lifecycle fact.

    This is deliberately a comparison of producer-owned fingerprints, not a
    second interpreter.  It reports the first stage that omitted or changed a
    confirmed semantic field without deciding whether the mission succeeded.
    """

    security = consume_runtime_security_evidence(events)
    envelopes = sorted(security.envelopes, key=lambda item: item.occurred_at)
    types = {item.event_type for item in envelopes}
    findings = list(security.findings)
    # Historic missions predate the versioned envelope.  Absence is not a
    # retrospective violation; only evaluate flow completeness once at least
    # one participating producer fact exists.
    if not envelopes:
        return RuntimeEvidenceConsumerResult(envelopes=(), findings=tuple(findings))
    stages = (
        ("mission_composition.confirmed", "composition"),
        ("execution_task.queued", "admission"),
        ("execution_task.started", "execution"),
    )
    for event_type, stage in stages:
        if event_type not in types:
            findings.append(
                {
                    "category": "intelligence_flow_gap",
                    "code": f"missing:{stage}:{event_type}",
                    "severity": "warning",
                }
            )
            break
    baseline: dict[str, str] | None = None
    for envelope in envelopes:
        causal = envelope.facts.get("causal_observation")
        if isinstance(causal, dict):
            constraints = causal.get("constraints")
            metadata = causal.get("safe_metadata")
            if isinstance(constraints, list) and "public_only" in constraints and isinstance(metadata, dict):
                public_count = metadata.get("verified_public_candidate_count", metadata.get("web_result_count"))
                internal_count = metadata.get("internal_count")
                if (
                    isinstance(public_count, int)
                    and isinstance(internal_count, int)
                    and public_count == 0
                    and internal_count > 0
                ):
                    findings.append(
                        {
                            "category": "intelligence_flow_divergence",
                            "code": f"source_partition_conflict:{envelope.event_id}",
                            "severity": "error",
                        }
                    )
        if envelope.event_type not in {item[0] for item in stages}:
            continue
        raw_lineage = envelope.facts.get("semantic_lineage")
        lineage = raw_lineage if isinstance(raw_lineage, dict) else {}
        typed_lineage = {str(key): str(value) for key, value in lineage.items() if isinstance(value, str)}
        if envelope.event_type == "mission_composition.confirmed":
            baseline = typed_lineage
            continue
        if baseline is None:
            continue
        for field, expected in baseline.items():
            observed = typed_lineage.get(field)
            if observed is None:
                findings.append(
                    {
                        "category": "intelligence_flow_gap",
                        "code": f"missing_lineage:{envelope.event_type}:{field}",
                        "severity": "warning",
                    }
                )
                return RuntimeEvidenceConsumerResult(envelopes=tuple(envelopes), findings=tuple(findings))
            if observed != expected:
                findings.append(
                    {
                        "category": "intelligence_flow_divergence",
                        "code": f"changed_lineage:{envelope.event_type}:{field}",
                        "severity": "error",
                    }
                )
                return RuntimeEvidenceConsumerResult(envelopes=tuple(envelopes), findings=tuple(findings))
    return RuntimeEvidenceConsumerResult(envelopes=tuple(envelopes), findings=tuple(findings))
