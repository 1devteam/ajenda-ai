from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend.services.runtime_evidence_ledger import RuntimeEvidenceLedger
from backend.services.ui_runtime_interaction_projection import (
    build_ui_runtime_interaction_projection,
    ui_interaction_projection_digest,
)


class _Session:
    def __init__(self) -> None:
        self.events = []

    def add(self, value: object) -> None:
        self.events.append(value)

    def flush(self) -> None:
        return None

    def refresh(self, value: object) -> None:
        return None


def _event(
    session: _Session,
    *,
    event_id: uuid.UUID,
    interaction_id: uuid.UUID,
    phase: str,
    origin: str,
    predecessor: uuid.UUID | None = None,
    persisted_at: datetime,
) -> object:
    return RuntimeEvidenceLedger(session).append_fact(
        event_id=event_id,
        tenant_id="tenant-a",
        mission_id=None,
        category="ui_interaction",
        action="browser_event" if origin == "browser_untrusted" else "server_event",
        producer="frontend.browser" if origin == "browser_untrusted" else "api.provider_credentials",
        actor="human:operator",
        details=f"{phase}",
        correlation_id=str(interaction_id),
        causation_id=str(predecessor) if predecessor else None,
        facts={
            "ui_interaction": {
                "schema_version": 1,
                "evidence_origin": origin,
                "action_id": "credential.linkedin.oauth.connect",
                "phase": phase,
                "predecessor_event_id": str(predecessor) if predecessor else None,
                "producer_sequence": 1 if origin == "browser_untrusted" else None,
                "producer_occurred_at": persisted_at.isoformat() if origin == "browser_untrusted" else None,
                "outcome_code": "OBSERVED",
            }
        },
        occurred_at=persisted_at,
    )


def test_projection_keeps_causal_predecessor_distinct_from_arrival_order() -> None:
    session = _Session()
    interaction_id = uuid.uuid4()
    when = datetime(2026, 10, 21, tzinfo=UTC)
    clicked_id = uuid.uuid4()
    request_id = uuid.uuid4()
    # Delayed browser click arrives after a server request. Receipt ordering is
    # retained, while the predecessor relationship remains the causal fact.
    _event(
        session,
        event_id=request_id,
        interaction_id=interaction_id,
        phase="ui.request_attempted",
        origin="browser_untrusted",
        predecessor=clicked_id,
        persisted_at=when,
    )
    _event(
        session,
        event_id=clicked_id,
        interaction_id=interaction_id,
        phase="ui.action_clicked",
        origin="browser_untrusted",
        persisted_at=when + timedelta(seconds=2),
    )

    projection = build_ui_runtime_interaction_projection(
        interaction_id=interaction_id,
        tenant_id="tenant-a",
        audit_events=session.events,
        now=when + timedelta(seconds=3),
    )

    assert projection.terminal_state == "in_progress"
    request = next(item for item in projection.events if item.event_id == request_id)
    assert request.predecessor_event_id == clicked_id
    assert "missing_causal_predecessor" not in " ".join(projection.contradictions)
    assert projection.first_divergence is None


def test_projection_marks_timeout_browser_gap_as_telemetry_unavailable_not_failure() -> None:
    session = _Session()
    interaction_id = uuid.uuid4()
    when = datetime(2026, 10, 21, tzinfo=UTC)
    _event(
        session,
        event_id=uuid.uuid4(),
        interaction_id=interaction_id,
        phase="api.request_received",
        origin="server_authoritative",
        persisted_at=when,
    )

    projection = build_ui_runtime_interaction_projection(
        interaction_id=interaction_id,
        tenant_id="tenant-a",
        audit_events=session.events,
        now=when + timedelta(minutes=16),
    )

    assert projection.terminal_state == "indeterminate"
    click_coverage = next(item for item in projection.coverage if item.stage == "ui.action_clicked")
    assert click_coverage.status == "telemetry_unavailable"
    assert projection.first_divergence == "ui.action_clicked"


def test_projection_records_completed_linkedin_lifecycle_without_sensitive_values() -> None:
    session = _Session()
    interaction_id = uuid.uuid4()
    when = datetime(2026, 10, 21, tzinfo=UTC)
    predecessor: uuid.UUID | None = None
    phases = (
        ("ui.action_clicked", "browser_untrusted"),
        ("ui.handler_entered", "browser_untrusted"),
        ("ui.request_attempted", "browser_untrusted"),
        ("api.request_received", "server_authoritative"),
        ("api.authentication_checked", "server_authoritative"),
        ("api.authorization_checked", "server_authoritative"),
        ("oauth.authorization_url_issued", "server_authoritative"),
        ("ui.redirect_assigned", "browser_untrusted"),
        ("api.callback_received", "server_authoritative"),
        ("oauth.credential_persisted", "server_authoritative"),
    )
    for offset, (phase, origin) in enumerate(phases):
        event_id = uuid.uuid4()
        _event(
            session,
            event_id=event_id,
            interaction_id=interaction_id,
            phase=phase,
            origin=origin,
            predecessor=predecessor,
            persisted_at=when + timedelta(seconds=offset),
        )
        predecessor = event_id

    projection = build_ui_runtime_interaction_projection(
        interaction_id=interaction_id,
        tenant_id="tenant-a",
        audit_events=session.events,
    )

    assert projection.terminal_state == "completed"
    assert all(item.status == "observed" for item in projection.coverage)
    assert projection.missing_evidence == []
    serialized = projection.model_dump_json()
    assert "https://" not in serialized
    assert "access_token" not in serialized
    assert '"state":' not in serialized
    assert projection.provenance.artifact_type == "graft_ui_runtime_interaction_evidence"
    assert projection.provenance.artifact_schema_version == "1.0.0"
    assert projection.provenance.sha256 == ui_interaction_projection_digest(projection)


def test_projection_classifies_exchange_failure_without_marking_prior_gaps_not_applicable() -> None:
    session = _Session()
    interaction_id = uuid.uuid4()
    when = datetime(2026, 10, 21, tzinfo=UTC)
    phases = (
        ("ui.action_clicked", "browser_untrusted"),
        ("ui.handler_entered", "browser_untrusted"),
        ("ui.request_attempted", "browser_untrusted"),
        ("api.request_received", "server_authoritative"),
        ("api.authentication_checked", "server_authoritative"),
        ("api.authorization_checked", "server_authoritative"),
        ("oauth.authorization_url_issued", "server_authoritative"),
        ("ui.redirect_assigned", "browser_untrusted"),
        ("api.callback_received", "server_authoritative"),
        ("oauth.exchange_failed", "server_authoritative"),
    )
    predecessor: uuid.UUID | None = None
    for offset, (phase, origin) in enumerate(phases):
        event_id = uuid.uuid4()
        _event(
            session,
            event_id=event_id,
            interaction_id=interaction_id,
            phase=phase,
            origin=origin,
            predecessor=predecessor,
            persisted_at=when + timedelta(seconds=offset),
        )
        predecessor = event_id

    projection = build_ui_runtime_interaction_projection(
        interaction_id=interaction_id,
        tenant_id="tenant-a",
        audit_events=session.events,
    )

    assert projection.terminal_state == "failed"
    assert all(item.status == "observed" for item in projection.coverage[:-1])
    persisted = next(item for item in projection.coverage if item.stage == "oauth.credential_persisted")
    assert persisted.status == "observed"
    assert persisted.reason == "terminal_outcome_observed"
    assert projection.missing_evidence == []
    assert projection.first_divergence is None
