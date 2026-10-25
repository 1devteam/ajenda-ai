"""Versioned runtime facts stored in Ajenda's existing append-only audit ledger.

This module deliberately does not introduce another event store.  ``AuditEvent``
is the durable fact owner; this service gives selected audit records a stable,
integrity-checked envelope that independent readers can consume.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.domain.audit_event import AuditEvent
from backend.repositories.audit_event_repository import AuditEventRepository

RUNTIME_EVIDENCE_SCHEMA_VERSION = 2
RUNTIME_CAUSAL_OBSERVATION_SCHEMA_VERSION = 1
RUNTIME_EVIDENCE_PAYLOAD_KEY = "runtime_evidence"
_INTEGRITY_ALGORITHM = "hmac-sha256"
_DEVELOPMENT_INTEGRITY_KEY = b"ajenda-development-runtime-evidence-key-not-for-production"


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
    integrity_algorithm: str = Field(min_length=1, max_length=64)
    integrity_key_id: str = Field(min_length=1, max_length=80)
    integrity_sha256: str


class RuntimeCausalObservation(BaseModel):
    """Typed, bounded decision facts carried by the existing audit ledger.

    This is an observation contract only.  It records why a component chose
    or rejected a path without granting the ledger any execution authority.
    Values that may contain customer or provider data are represented by
    references, counts, or hashes at the producer boundary.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = RUNTIME_CAUSAL_OBSERVATION_SCHEMA_VERSION
    stage: str = Field(min_length=1, max_length=120)
    decision: str = Field(min_length=1, max_length=160)
    reason_code: str = Field(min_length=1, max_length=160)
    transformation_id: str | None = Field(default=None, max_length=160)
    alternatives: tuple[str, ...] = ()
    selected_path: str | None = Field(default=None, max_length=160)
    rejected_paths: tuple[str, ...] = ()
    source_provenance: dict[str, str] = Field(default_factory=dict)
    field_lineage: dict[str, str] = Field(default_factory=dict)
    constraints: tuple[str, ...] = ()
    safe_metadata: dict[str, Any] = Field(default_factory=dict)


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _integrity_hash(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()


def _integrity_key_candidates() -> tuple[bytes, ...]:
    """Return keys held outside the audit database, newest key first.

    Production already requires the runtime-secret key and keeps it in the
    deployment secret boundary.  Deriving the ledger MAC key from that owner
    avoids a second secret authority while allowing the configured previous
    key to verify records written immediately before rotation.  A fixed key is
    permitted only outside production so local/test evidence remains usable.
    """

    settings = get_settings()
    current = str(settings.runtime_secret_encryption_key or "").strip()
    previous = str(settings.runtime_secret_encryption_key_prev or "").strip()
    keys = tuple(value.encode("utf-8") for value in (current, previous) if value)
    if keys:
        return keys
    if settings.env == "production":
        raise RuntimeError("runtime evidence requires AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY in production")
    return (_DEVELOPMENT_INTEGRITY_KEY,)


def _integrity_key_id(key: bytes) -> str:
    return "sha256:" + hashlib.sha256(b"ajenda-runtime-evidence-key-id\0" + key).hexdigest()[:24]


def _integrity_mac(payload: Mapping[str, Any], key: bytes) -> str:
    return "hmac-sha256:" + hmac.new(key, _canonical_json(payload), hashlib.sha256).hexdigest()


def _string_references(payload: Mapping[str, Any]) -> dict[str, str]:
    """Retain causal IDs without copying arbitrary, potentially sensitive payloads."""

    allowed = ("task_id", "lease_id", "proposal_id", "plan_id", "dispatch_id", "grant_id", "evidence_id")
    return {key: str(payload[key]) for key in allowed if payload.get(key) is not None}


def semantic_lineage_from_mission_metadata(metadata: Mapping[str, Any]) -> dict[str, str]:
    """Return a minimised, stable semantic handoff fingerprint.

    The source instruction stays in the mission intake owner.  This projection
    carries only keyed digests so downstream facts can prove whether objective,
    target scope, outcomes, constraints, and success criteria changed.
    """

    intake = metadata.get("mission_intake")
    intake = intake if isinstance(intake, dict) else {}
    context = intake.get("context")
    context = context if isinstance(context, dict) else {}
    composition = context.get("composition")
    composition = composition if isinstance(composition, dict) else {}
    intent = composition.get("intent")
    intent = intent if isinstance(intent, dict) else {}
    values: dict[str, Any] = {
        "instruction": composition.get("instruction"),
        "objective": intent.get("objective") or composition.get("objective"),
        "target_entities": intent.get("target_entities"),
        "requested_outcomes": intent.get("requested_outcomes"),
        "constraints": intake.get("constraints"),
        "success_criteria": intake.get("success_criteria"),
    }
    semantic_snapshot = composition.get("semantic_snapshot")
    semantic_snapshot = semantic_snapshot if isinstance(semantic_snapshot, dict) else {}
    assessment_reference = semantic_snapshot.get("business_need_assessment_reference")
    assessment_reference = assessment_reference if isinstance(assessment_reference, dict) else {}
    response_advancement = assessment_reference.get("response_advancement")
    if isinstance(response_advancement, dict):
        # Keep the direct, tenant-owned identifiers in mission metadata.  The
        # runtime ledger receives only a digest of this non-authoritative
        # provenance package, so a later evidence reader can establish that
        # the queued task retained the same assessment/candidate/baseline
        # lineage without turning it into a measurement or impact claim.
        values["response_advancement"] = response_advancement
    return {
        name: "sha256:" + hashlib.sha256(_canonical_json({name: value})).hexdigest()
        for name, value in values.items()
        if value not in (None, [], {}, "")
    }


class RuntimeEvidenceLedger:
    """Append producer facts to ``audit_events`` with a stable envelope.

    The ledger has no read-side policy or orchestration authority.  Consumers
    should use :meth:`read_envelope` and derive their own findings.
    """

    def __init__(
        self,
        session: Session,
        *,
        audit_repository: AuditEventRepository | None = None,
        integrity_key: bytes | None = None,
        previous_integrity_keys: Sequence[bytes] = (),
        flush: bool = True,
    ) -> None:
        self._audit = audit_repository or AuditEventRepository(session)
        self._flush = flush
        self._integrity_keys = (
            (integrity_key, *previous_integrity_keys) if integrity_key else _integrity_key_candidates()
        )

    def append_fact(
        self,
        *,
        event_id: uuid.UUID | None = None,
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
        event_id = event_id or uuid.uuid4()
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
        envelope = {
            **unsigned,
            "integrity_algorithm": _INTEGRITY_ALGORITHM,
            "integrity_key_id": _integrity_key_id(self._integrity_keys[0]),
        }
        envelope["integrity_sha256"] = _integrity_mac(envelope, self._integrity_keys[0])
        event = AuditEvent(
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
        if self._flush:
            return self._audit.append(event)
        return self._audit.append_unflushed(event)

    def append_causal_observation(
        self,
        *,
        tenant_id: str,
        mission_id: uuid.UUID | None,
        producer: str,
        actor: str,
        observation: RuntimeCausalObservation,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        evidence_references: Sequence[str] = (),
    ) -> AuditEvent:
        """Persist a validated causal observation as a producer-owned fact."""

        return self.append_fact(
            tenant_id=tenant_id,
            mission_id=mission_id,
            category="runtime_decision",
            action=observation.stage,
            producer=producer,
            actor=actor,
            details=f"Observed {observation.decision} ({observation.reason_code})",
            facts={"causal_observation": observation.model_dump(mode="json")},
            authority_context={"authority_class": "observation", "grants_execution_authority": False},
            causation_id=causation_id,
            correlation_id=correlation_id,
            evidence_references=evidence_references,
        )

    @staticmethod
    def read_envelope(event: AuditEvent) -> RuntimeEvidenceEnvelope | None:
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        raw = payload.get(RUNTIME_EVIDENCE_PAYLOAD_KEY)
        if not isinstance(raw, dict):
            return None
        integrity = raw.get("integrity_sha256")
        unsigned = {key: value for key, value in raw.items() if key != "integrity_sha256"}
        if not isinstance(integrity, str):
            return None
        schema_version = raw.get("schema_version")
        if schema_version == 1:
            # Read historical v1 envelopes but never let them masquerade as a
            # tamper-resistant v2 record. They existed before keyed integrity.
            if integrity != _integrity_hash(unsigned):
                return None
            raw = {**raw, "integrity_algorithm": "sha256", "integrity_key_id": "legacy-v1"}
        elif schema_version == RUNTIME_EVIDENCE_SCHEMA_VERSION:
            if raw.get("integrity_algorithm") != _INTEGRITY_ALGORITHM:
                return None
            for key in _integrity_key_candidates():
                if hmac.compare_digest(integrity, _integrity_mac(unsigned, key)):
                    break
            else:
                return None
        else:
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
