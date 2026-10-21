"""Read-only verification of a fixed, pre-cutover development-signed evidence inventory.

A legacy-verified envelope is historical information, NOT trusted runtime evidence.
Do not use it to establish admission, authorization, execution or idempotency.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from backend.domain.audit_event import AuditEvent
from backend.services.runtime_evidence_ledger import (
    _DEVELOPMENT_INTEGRITY_KEY,
    RUNTIME_EVIDENCE_PAYLOAD_KEY,
    RUNTIME_EVIDENCE_SCHEMA_VERSION,
    RuntimeEvidenceEnvelope,
    _integrity_key_id,
    _integrity_mac,
)

# Verified inventory of 6,796 pre-cutover records, captured 2026-10-21.
PINNED_MANIFEST_SHA256 = "5b796aea2e031f0314c551410a2cd0eb577a62383d95281b4f9705a766fd001b"
PINNED_MANIFEST_RECORD_COUNT = 6796


@dataclass(frozen=True, slots=True)
class LegacyEvidenceResult:
    """A historical observation. This result grants no operational authority."""

    envelope: RuntimeEvidenceEnvelope
    trust_class: Literal["legacy_verified"] = "legacy_verified"


class LegacyRuntimeEvidenceVerifier:
    """Verify a pinned manifest and the original development-key HMAC.

    The manifest must be provisioned independently of the audit database and
    protected against unauthorized replacement. No implicit runtime fallback.
    """

    def __init__(self, manifest_path: Path) -> None:
        raw = Path(manifest_path).read_bytes()
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), PINNED_MANIFEST_SHA256):
            raise ValueError("Legacy evidence manifest fingerprint mismatch")
        entries = json.loads(raw)
        if not isinstance(entries, list) or len(entries) != PINNED_MANIFEST_RECORD_COUNT:
            raise ValueError("Legacy evidence manifest inventory mismatch")
        inventory: dict[str, tuple[str, str]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"event_id", "key_id", "signature"}:
                raise ValueError("Malformed legacy evidence manifest entry")
            event_id, key_id, signature = (entry[k] for k in ("event_id", "key_id", "signature"))
            if not all(isinstance(v, str) for v in (event_id, key_id, signature)):
                raise ValueError("Malformed legacy evidence manifest value")
            if event_id in inventory:
                raise ValueError("Duplicate legacy evidence event")
            inventory[event_id] = (key_id, signature)
        self._inventory = inventory

    def verify(self, event: AuditEvent) -> LegacyEvidenceResult | None:
        """Verify exact inventory membership, HMAC, and event-column binding."""
        recorded = self._inventory.get(str(event.id))
        if recorded is None:
            return None
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        raw = payload.get(RUNTIME_EVIDENCE_PAYLOAD_KEY)
        if not isinstance(raw, dict):
            return None
        if raw.get("schema_version") != RUNTIME_EVIDENCE_SCHEMA_VERSION:
            return None
        if raw.get("integrity_algorithm") != "hmac-sha256":
            return None
        expected_key_id = _integrity_key_id(_DEVELOPMENT_INTEGRITY_KEY)
        key_id, signature = recorded
        actual_id = raw.get("integrity_key_id")
        actual_signature = raw.get("integrity_sha256")
        if (
            key_id != expected_key_id
            or not isinstance(actual_id, str)
            or not hmac.compare_digest(actual_id, key_id)
            or not isinstance(actual_signature, str)
            or not hmac.compare_digest(actual_signature, signature)
        ):
            return None
        unsigned = {k: v for k, v in raw.items() if k != "integrity_sha256"}
        if not hmac.compare_digest(actual_signature, _integrity_mac(unsigned, _DEVELOPMENT_INTEGRITY_KEY)):
            return None
        try:
            envelope = RuntimeEvidenceEnvelope.model_validate(raw)
        except ValueError:
            return None
        if (
            envelope.event_id != event.id
            or envelope.tenant_id != event.tenant_id
            or envelope.mission_id != event.mission_id
            or envelope.event_type != f"{event.category}.{event.action}"
        ):
            return None
        return LegacyEvidenceResult(envelope=envelope)
