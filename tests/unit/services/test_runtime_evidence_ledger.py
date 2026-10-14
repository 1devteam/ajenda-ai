from __future__ import annotations

import uuid
from datetime import UTC, datetime

from backend.services.runtime_evidence_consumers import (
    consume_intelligence_flow_evidence,
    consume_runtime_security_evidence,
)
from backend.services.runtime_evidence_ledger import RuntimeEvidenceLedger


class _Session:
    def __init__(self) -> None:
        self.events = []

    def add(self, value: object) -> None:
        self.events.append(value)

    def flush(self) -> None:
        return None

    def refresh(self, value: object) -> None:
        return None


def test_runtime_evidence_envelope_is_versioned_integrity_checked_and_minimised() -> None:
    session = _Session()
    mission_id = uuid.uuid4()

    event = RuntimeEvidenceLedger(session).append_fact(
        tenant_id="tenant-a",
        mission_id=mission_id,
        category="execution_task",
        action="queued",
        producer="execution_coordinator",
        actor="operator-a",
        details="queued",
        facts={"task_id": "task-a", "raw_provider_response": "not copied into references"},
        authority_context={"policy_allowed": True},
        causation_id="task-a",
        correlation_id=str(mission_id),
        occurred_at=datetime(2026, 10, 13, tzinfo=UTC),
    )

    envelope = RuntimeEvidenceLedger.read_envelope(event)
    assert envelope is not None
    assert envelope.schema_version == 1
    assert envelope.event_id == event.id
    assert envelope.event_type == "execution_task.queued"
    assert envelope.subject_references == {"task_id": "task-a"}
    assert envelope.authority_context == {"policy_allowed": True}


def test_runtime_evidence_reader_rejects_tampered_envelope() -> None:
    session = _Session()
    event = RuntimeEvidenceLedger(session).append_fact(
        tenant_id="tenant-a",
        mission_id=None,
        category="worker",
        action="task_failed",
        producer="worker_runtime",
        actor="worker-a",
        details="failed",
        facts={"task_id": "task-a"},
    )
    event.payload_json["runtime_evidence"]["facts"]["task_id"] = "forged"  # type: ignore[index]

    assert RuntimeEvidenceLedger.read_envelope(event) is None


def test_independent_consumers_preserve_facts_and_report_missing_lifecycle_stage() -> None:
    session = _Session()
    event = RuntimeEvidenceLedger(session).append_fact(
        tenant_id="tenant-a",
        mission_id=None,
        category="mission_composition",
        action="confirmed",
        producer="composition",
        actor="operator-a",
        details="confirmed",
    )

    security = consume_runtime_security_evidence([event])
    intelligence = consume_intelligence_flow_evidence([event])

    assert len(security.envelopes) == 1
    assert security.findings == ()
    assert [finding["code"] for finding in intelligence.findings] == ["missing:admission:execution_task.queued"]
