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
    """Expose first missing lifecycle fact; never infer a business outcome."""

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
    return RuntimeEvidenceConsumerResult(envelopes=tuple(envelopes), findings=tuple(findings))
