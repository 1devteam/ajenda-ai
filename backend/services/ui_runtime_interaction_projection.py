"""Read-only causal projection for consequential UI interactions."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.domain.audit_event import AuditEvent
from backend.services.runtime_evidence_ledger import RuntimeEvidenceLedger

UI_RUNTIME_INTERACTION_PROJECTION_SCHEMA_VERSION = 1
_EXPECTED_LINKEDIN_STAGES = (
    "ui.action_clicked",
    "ui.handler_entered",
    "ui.request_attempted",
    "api.request_received",
    "api.authentication_checked",
    "api.authorization_checked",
    "oauth.authorization_url_issued",
    "ui.redirect_assigned",
    "api.callback_received",
    "oauth.credential_persisted",
)
_TERMINAL_BY_STAGE = {
    "api.authorization_denied": "denied",
    "oauth.authorization_failed": "failed",
    "oauth.exchange_failed": "failed",
    "oauth.credential_persisted": "completed",
    "ui.action_abandoned": "abandoned",
}
# A terminal fact may be emitted between two expected success-path stages.
# These positions describe applicability; they do not infer that an omitted
# stage executed.  This makes a known denied/failed path distinct from a
# telemetry gap on a path that should have continued.
_TERMINAL_EXPECTED_STAGE_POSITION = {
    "api.authorization_denied": 5,
    "oauth.authorization_failed": 6,
    "oauth.exchange_failed": 9,
    "oauth.credential_persisted": 9,
    "ui.action_abandoned": 2,
}
_TERMINAL_COVERS_EXPECTED_STAGE = {
    "api.authorization_denied": "api.authorization_checked",
    "oauth.authorization_failed": "oauth.authorization_url_issued",
    "oauth.exchange_failed": "oauth.credential_persisted",
    "ui.action_abandoned": "ui.request_attempted",
}


class UIInteractionProjectionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    phase: str
    evidence_origin: Literal["browser_untrusted", "server_authoritative"]
    action_id: str
    outcome_code: str | None = None
    predecessor_event_id: UUID | None = None
    producer_sequence: int | None = None
    producer_occurred_at: datetime | None = None
    persisted_at: datetime


class UIInteractionCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    applicable: bool
    status: Literal["observed", "not_observed", "not_applicable", "pending", "telemetry_unavailable"]
    reason: str


class UIInteractionProjectionProvenance(BaseModel):
    """Digest provenance for a read-only, G.R.A.F.T.-compatible export."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_type: Literal["graft_ui_runtime_interaction_evidence"] = "graft_ui_runtime_interaction_evidence"
    artifact_schema_version: Literal["1.0.0"] = "1.0.0"
    exported_at: datetime
    producer: Literal["ajenda.ui_runtime_interaction_projection"] = "ajenda.ui_runtime_interaction_projection"
    producer_version: Literal["1"] = "1"
    source_event_ids: tuple[str, ...]
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class UIInteractionRuntimeEvidenceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    interaction_id: UUID
    tenant_id: str
    action_id: str | None = None
    terminal_state: Literal["completed", "denied", "failed", "abandoned", "indeterminate", "in_progress"]
    timeout_at: datetime | None = None
    read_only: Literal[True] = True
    grants_execution_authority: Literal[False] = False
    events: list[UIInteractionProjectionEvent] = Field(default_factory=list)
    coverage: list[UIInteractionCoverage] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    historical_unknown: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    first_divergence: str | None = None
    provenance: UIInteractionProjectionProvenance


def ui_interaction_projection_digest(projection: UIInteractionRuntimeEvidenceProjection) -> str:
    """Return the digest of the exported projection excluding its own digest."""

    payload = projection.model_dump(mode="json", exclude={"provenance": {"sha256"}})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _seal_projection(
    projection: UIInteractionRuntimeEvidenceProjection,
    *,
    exported_at: datetime,
) -> UIInteractionRuntimeEvidenceProjection:
    provenance = UIInteractionProjectionProvenance(
        exported_at=exported_at,
        source_event_ids=tuple(sorted(str(event.event_id) for event in projection.events)),
        sha256="sha256:" + "0" * 64,
    )
    unsealed = projection.model_copy(update={"provenance": provenance})
    return unsealed.model_copy(
        update={"provenance": provenance.model_copy(update={"sha256": ui_interaction_projection_digest(unsealed)})}
    )


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def build_ui_runtime_interaction_projection(
    *,
    interaction_id: UUID,
    tenant_id: str,
    audit_events: list[AuditEvent],
    now: datetime | None = None,
    timeout: timedelta = timedelta(minutes=15),
) -> UIInteractionRuntimeEvidenceProjection:
    """Reconcile persisted UI/API facts without inferring absent browser work.

    Persisted receipt order is intentionally not causal order.  The projection
    retains predecessor references and producer sequence; expected-stage order
    is used only to identify the first supported gap.
    """

    records: list[UIInteractionProjectionEvent] = []
    contradictions: list[str] = []
    for event in audit_events:
        if event.tenant_id != tenant_id:
            continue
        envelope = RuntimeEvidenceLedger.read_envelope(event)
        if envelope is None or envelope.correlation_id != str(interaction_id):
            continue
        raw = envelope.facts.get("ui_interaction")
        if not isinstance(raw, dict):
            continue
        origin = raw.get("evidence_origin")
        phase = raw.get("phase")
        action_id = raw.get("action_id")
        if (
            origin not in {"browser_untrusted", "server_authoritative"}
            or not isinstance(phase, str)
            or not isinstance(action_id, str)
        ):
            contradictions.append(f"event:{event.id}:malformed_ui_interaction_fact")
            continue
        predecessor = raw.get("predecessor_event_id")
        try:
            predecessor_id = UUID(predecessor) if isinstance(predecessor, str) else None
        except ValueError:
            contradictions.append(f"event:{event.id}:invalid_predecessor")
            predecessor_id = None
        sequence = raw.get("producer_sequence")
        records.append(
            UIInteractionProjectionEvent(
                event_id=event.id,
                phase=phase,
                evidence_origin=origin,
                action_id=action_id,
                outcome_code=raw.get("outcome_code") if isinstance(raw.get("outcome_code"), str) else None,
                predecessor_event_id=predecessor_id,
                producer_sequence=sequence if isinstance(sequence, int) else None,
                producer_occurred_at=_parse_time(raw.get("producer_occurred_at")),
                persisted_at=event.created_at,
            )
        )

    # Receipt time is the only reliable ordering value.  It is deliberately
    # not used to infer causation; causal links are preserved above.
    records.sort(key=lambda item: (item.persisted_at, str(item.event_id)))
    action_id = records[0].action_id if records else None
    phases = {item.phase for item in records}
    event_ids = {item.event_id for item in records}
    for item in records:
        if item.predecessor_event_id is not None and item.predecessor_event_id not in event_ids:
            contradictions.append(f"event:{item.event_id}:missing_causal_predecessor")

    terminal_state: Literal["completed", "denied", "failed", "abandoned", "indeterminate", "in_progress"]
    terminal_state = "in_progress"
    for phase, state in _TERMINAL_BY_STAGE.items():
        if phase in phases:
            terminal_state = state  # type: ignore[assignment]
            break
    started_at = min((item.persisted_at for item in records), default=None)
    timeout_at = started_at + timeout if started_at else None
    evaluation_time = now or datetime.now(UTC)
    if terminal_state == "in_progress" and timeout_at is not None and evaluation_time >= timeout_at:
        terminal_state = "indeterminate"

    coverage: list[UIInteractionCoverage] = []
    missing: list[str] = []
    terminal_phases = tuple(phase for phase in _TERMINAL_BY_STAGE if phase in phases)
    terminal_index = next(
        (_TERMINAL_EXPECTED_STAGE_POSITION[phase] for phase in terminal_phases),
        None,
    )
    terminal_covered_stage = next(
        (
            _TERMINAL_COVERS_EXPECTED_STAGE[phase]
            for phase in terminal_phases
            if phase in _TERMINAL_COVERS_EXPECTED_STAGE
        ),
        None,
    )
    for index, stage in enumerate(_EXPECTED_LINKEDIN_STAGES):
        if stage in phases:
            coverage.append(
                UIInteractionCoverage(stage=stage, applicable=True, status="observed", reason="persisted_fact")
            )
            continue
        if stage == terminal_covered_stage:
            coverage.append(
                UIInteractionCoverage(
                    stage=stage,
                    applicable=True,
                    status="observed",
                    reason="terminal_outcome_observed",
                )
            )
            continue
        if terminal_state in {"denied", "failed", "abandoned"}:
            # Stages after a recorded terminal outcome never became applicable.
            if terminal_index is None or index > terminal_index:
                coverage.append(
                    UIInteractionCoverage(
                        stage=stage, applicable=False, status="not_applicable", reason="terminal_path"
                    )
                )
                continue
        if terminal_state == "in_progress":
            coverage.append(
                UIInteractionCoverage(stage=stage, applicable=True, status="pending", reason="interaction_open")
            )
            continue
        if terminal_state == "indeterminate":
            status: Literal["not_observed", "telemetry_unavailable"] = (
                "telemetry_unavailable" if stage.startswith("ui.") else "not_observed"
            )
            coverage.append(
                UIInteractionCoverage(stage=stage, applicable=True, status=status, reason="interaction_timeout")
            )
            missing.append(stage)
            continue
        coverage.append(
            UIInteractionCoverage(stage=stage, applicable=True, status="not_observed", reason="terminal_path_gap")
        )
        missing.append(stage)

    first_divergence = next(
        (item.stage for item in coverage if item.status in {"not_observed", "telemetry_unavailable"}),
        None,
    )
    if first_divergence is None:
        first_divergence = next(iter(sorted(set(contradictions))), None)
    projection = UIInteractionRuntimeEvidenceProjection(
        interaction_id=interaction_id,
        tenant_id=tenant_id,
        action_id=action_id,
        terminal_state=terminal_state,
        timeout_at=timeout_at,
        events=records,
        coverage=coverage,
        missing_evidence=sorted(set(missing)),
        contradictions=sorted(set(contradictions)),
        first_divergence=first_divergence,
        provenance=UIInteractionProjectionProvenance(
            exported_at=evaluation_time,
            source_event_ids=(),
            sha256="sha256:" + "0" * 64,
        ),
    )
    return _seal_projection(projection, exported_at=evaluation_time)
