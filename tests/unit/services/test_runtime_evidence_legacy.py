"""Regression checks for explicit, non-authoritative historical verification."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.services import runtime_evidence_legacy as legacy
from backend.services.runtime_evidence_ledger import (
    _DEVELOPMENT_INTEGRITY_KEY,
    _integrity_key_id,
    _integrity_mac,
)


def _fixture(tmp_path, monkeypatch):
    event_id = uuid.uuid4()
    unsigned = {
        "schema_version": 2,
        "event_id": str(event_id),
        "event_type": "execution_task.queued",
        "producer": "fixture",
        "occurred_at": datetime(2026, 10, 20, tzinfo=UTC).isoformat(),
        "tenant_id": "tenant-a",
        "mission_id": None,
        "causation_id": None,
        "correlation_id": None,
        "authority_context": {},
        "subject_references": {"task_id": "task-a"},
        "facts": {"task_id": "task-a"},
        "evidence_references": [],
        "integrity_algorithm": "hmac-sha256",
        "integrity_key_id": _integrity_key_id(_DEVELOPMENT_INTEGRITY_KEY),
    }
    signature = _integrity_mac(unsigned, _DEVELOPMENT_INTEGRITY_KEY)
    event = SimpleNamespace(
        id=event_id,
        tenant_id="tenant-a",
        mission_id=None,
        category="execution_task",
        action="queued",
        payload_json={"runtime_evidence": {**unsigned, "integrity_sha256": signature}},
    )
    record = {"event_id": str(event_id), "key_id": unsigned["integrity_key_id"], "signature": signature}
    raw = json.dumps([record], sort_keys=True, separators=(",", ":")).encode()
    path = tmp_path / "legacy.json"
    path.write_bytes(raw)
    monkeypatch.setattr(legacy, "PINNED_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())
    monkeypatch.setattr(legacy, "PINNED_MANIFEST_RECORD_COUNT", 1)
    return path, event


def test_matching_event_is_legacy_verified(tmp_path, monkeypatch):
    path, event = _fixture(tmp_path, monkeypatch)
    result = legacy.LegacyRuntimeEvidenceVerifier(path).verify(event)
    assert result is not None
    assert result.trust_class == "legacy_verified"
    assert result.envelope.subject_references == {"task_id": "task-a"}


def test_tampered_payload_rejected(tmp_path, monkeypatch):
    path, event = _fixture(tmp_path, monkeypatch)
    verifier = legacy.LegacyRuntimeEvidenceVerifier(path)
    event.payload_json["runtime_evidence"]["facts"]["task_id"] = "altered"
    assert verifier.verify(event) is None


def test_unknown_event_id_rejected(tmp_path, monkeypatch):
    path, event = _fixture(tmp_path, monkeypatch)
    verifier = legacy.LegacyRuntimeEvidenceVerifier(path)
    event.id = uuid.uuid4()
    assert verifier.verify(event) is None


def test_manifest_replacement_rejected(tmp_path, monkeypatch):
    path, _ = _fixture(tmp_path, monkeypatch)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        legacy.LegacyRuntimeEvidenceVerifier(path)


def test_event_binding_mismatch_rejected(tmp_path, monkeypatch):
    path, event = _fixture(tmp_path, monkeypatch)
    verifier = legacy.LegacyRuntimeEvidenceVerifier(path)
    event.tenant_id = "tenant-b"
    assert verifier.verify(event) is None


def test_existing_strict_reader_does_not_trust_legacy(tmp_path, monkeypatch):
    from backend.services import runtime_evidence_ledger as ledger

    path, event = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(ledger, "_integrity_key_candidates", lambda: (b"different-runtime-key",))
    assert ledger.RuntimeEvidenceLedger.read_envelope(event) is None
    assert legacy.LegacyRuntimeEvidenceVerifier(path).verify(event) is not None
