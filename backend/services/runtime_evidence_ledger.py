"""Versioned runtime facts stored in Ajenda's existing append-only audit ledger.

This module deliberately does not introduce another event store.  ``AuditEvent``
is the durable fact owner; this service gives selected audit records a stable,
integrity-checked envelope that independent readers can consume.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.repositories.audit_event_repository import AuditEventRepository

RUNTIME_EVIDENCE_SCHEMA_VERSION = 1
RUNTIME_EVIDENCE_PAYLOAD_KEY = "runtime_evidence"


class RuntimeEvidenceEnvelope(BaseModel):
    """Portable, versioned description of a producer-owned runtime fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = RUNTIME_EVIDENCE_SCHEMA_VERSION
    event_id: uuid.UUID
    event_type: str = Field(min_length=3, max_length=255)
    producer: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    tenant_id: str = Field(min_length=1, max_length=128)
    mission_id: uuid.UUID | None = None
    causation_id: str | None = Field(default=None, max_length=255)
    correlation_id: str | None = Field(default=None, max_length=255)
    authority_context: dict[str, Any] = Field(default_factory=dict)
    subject_references: dict[str, str] = Field(default_factory=dict)
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence_references: tuple[str, ...] = ()
    integrity_sha256: str


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _integrity_hash(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _string_references(payload: Mapping[str, Any]) -> dict[str, str]:
    """Retain causal IDs without copying arbitrary, potentially sensitive payloads."""

    allowed = ("task_id", "lease_id", "proposal_id", "plan_id", "dispatch_id", "grant_id", "evidence_id")
    return {key: str(payload[key]) for key in allowed if payload.get(key) is not None}


class RuntimeEvidenceLedger:
    """Append producer facts to ``audit_events`` with a stable envelope.

    The ledger has no read-side policy or orchestration authority.  Consumers
    should use :meth:`read_envelope` and derive their own findings.
    """

    def __init__(self, session: Session, *, audit_repository: AuditEventRepository | None = None) -> None:
        self._audit = audit_repository or AuditEventRepository(session)

    def append_fact(
        self,
        *,
        tenant_id: str,
        mission_id: uuid.UUID | None,
        category: str,
        action: str,
        producer: str,
        actor: str,
        details: str,
        facts: Mapping[str, Any] | None = None,
        authority_context: Mapping[str, Any] | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        evidence_references: Sequence[str] = (),
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        event_id = uuid.uuid4()
        when = occurred_at or datetime.now(UTC)
        if when.tzinfo is None:
            raise ValueError("runtime evidence occurred_at must be timezone-aware")
        fact_payload = dict(facts or {})
        unsigned = {
            "schema_version": RUNTIME_EVIDENCE_SCHEMA_VERSION,
            "event_id": str(event_id),
            "event_type": f"{category}.{action}",
            "producer": producer,
            "occurred_at": when.isoformat(),
            "tenant_id": tenant_id,
            "mission_id": str(mission_id) if mission_id is not None else None,
            "causation_id": causation_id,
            "correlation_id": correlation_id,
            "authority_context": dict(authority_context or {}),
            "subject_references": _string_references(fact_payload),
            "facts": fact_payload,
            "evidence_references": [str(item) for item in evidence_references],
        }
        envelope = {**unsigned, "integrity_sha256": _integrity_hash(unsigned)}
        return self._audit.append(
            AuditEvent(
                id=event_id,
                tenant_id=tenant_id,
                mission_id=mission_id,
                category=category,
                action=action,
                actor=actor,
                details=details,
                payload_json={**fact_payload, RUNTIME_EVIDENCE_PAYLOAD_KEY: envelope},
                created_at=when,
            )
        )

    @staticmethod
    def read_envelope(event: AuditEvent) -> RuntimeEvidenceEnvelope | None:
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        raw = payload.get(RUNTIME_EVIDENCE_PAYLOAD_KEY)
        if not isinstance(raw, dict):
            return None
        integrity = raw.get("integrity_sha256")
        unsigned = {key: value for key, value in raw.items() if key != "integrity_sha256"}
        if not isinstance(integrity, str) or integrity != _integrity_hash(unsigned):
            return None
        envelope = RuntimeEvidenceEnvelope.model_validate(raw)
        if (
            envelope.event_id != event.id
            or envelope.tenant_id != event.tenant_id
            or envelope.mission_id != event.mission_id
            or envelope.event_type != f"{event.category}.{event.action}"
        ):
            return None
        return envelope
