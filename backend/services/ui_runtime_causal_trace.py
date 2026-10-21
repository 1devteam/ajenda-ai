"""Bounded UI-to-runtime causal evidence on Ajenda's audit ledger.

Browser events are explicitly untrusted observations.  They are useful for
diagnosis only; authenticated API routes retain all execution authority.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.domain.audit_event import AuditEvent
from backend.repositories.audit_event_repository import AuditEventRepository
from backend.services.runtime_evidence_ledger import RuntimeEvidenceLedger

UI_INTERACTION_SCHEMA_VERSION = 1
LINKEDIN_OAUTH_ACTION_ID = "credential.linkedin.oauth.connect"

BrowserPhase = Literal[
    "ui.action_clicked",
    "ui.handler_entered",
    "ui.request_attempted",
    "ui.redirect_assigned",
    "ui.action_abandoned",
]
ServerPhase = Literal[
    "api.request_received",
    "api.authentication_checked",
    "api.authorization_checked",
    "api.authorization_denied",
    "oauth.authorization_url_issued",
    "oauth.authorization_failed",
    "api.callback_received",
    "oauth.credential_persisted",
    "oauth.exchange_failed",
]


class BrowserInteractionEvent(BaseModel):
    """Redacted browser observation accepted by the telemetry boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: uuid.UUID
    local_interaction_id: uuid.UUID
    server_interaction_id: uuid.UUID | None = None
    action_id: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,159}$")
    phase: BrowserPhase
    predecessor_event_id: uuid.UUID | None = None
    producer_sequence: int = Field(ge=1, le=1_000_000)
    occurred_at: datetime
    outcome_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_:-]{2,120}$")

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("browser occurred_at must be timezone-aware")
        return value


class UIInteractionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    event_id: uuid.UUID
    server_interaction_id: uuid.UUID
    acknowledgement: Literal["persisted"] = "persisted"
    persisted_at: datetime
    duplicate: bool = False


class UIInteractionTraceError(ValueError):
    """A malformed or cross-interaction causal reference."""


def _browser_fact(event: BrowserInteractionEvent) -> dict[str, object]:
    return {
        "schema_version": UI_INTERACTION_SCHEMA_VERSION,
        "evidence_origin": "browser_untrusted",
        "event_id": str(event.event_id),
        "local_interaction_id": str(event.local_interaction_id),
        "server_interaction_id": str(event.server_interaction_id) if event.server_interaction_id else None,
        "action_id": event.action_id,
        "phase": event.phase,
        "predecessor_event_id": str(event.predecessor_event_id) if event.predecessor_event_id else None,
        "producer_sequence": event.producer_sequence,
        "producer_occurred_at": event.occurred_at.astimezone(UTC).isoformat(),
        "outcome_code": event.outcome_code,
    }


def _read_ui_fact(event: AuditEvent) -> dict[str, object] | None:
    envelope = RuntimeEvidenceLedger.read_envelope(event)
    if envelope is None or envelope.event_type != "ui_interaction.browser_event":
        return None
    fact = envelope.facts.get("ui_interaction")
    return fact if isinstance(fact, dict) else None


class UIInteractionTraceService:
    """Append and correlate interaction facts without execution authority."""

    def __init__(self, session: Session, *, audit_repository: AuditEventRepository | None = None) -> None:
        self._session = session
        self._audit = audit_repository or AuditEventRepository(session)

    def accept_browser_event(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        event: BrowserInteractionEvent,
    ) -> UIInteractionReceipt:
        existing = self._audit.get_for_tenant(event_id=event.event_id, tenant_id=tenant_id)
        if existing is not None:
            fact = _read_ui_fact(existing)
            if (
                fact is None
                or fact.get("event_id") != str(event.event_id)
                or fact.get("local_interaction_id") != str(event.local_interaction_id)
                or fact.get("action_id") != event.action_id
                or fact.get("phase") != event.phase
            ):
                raise UIInteractionTraceError("UI_INTERACTION_EVENT_ID_CONFLICT")
            correlation = RuntimeEvidenceLedger.read_envelope(existing)
            if correlation is None or correlation.correlation_id is None:
                raise UIInteractionTraceError("UI_INTERACTION_CORRELATION_MISSING")
            return UIInteractionReceipt(
                event_id=event.event_id,
                server_interaction_id=uuid.UUID(correlation.correlation_id),
                persisted_at=existing.created_at,
                duplicate=True,
            )

        server_interaction_id = event.server_interaction_id or uuid.uuid4()
        if event.server_interaction_id is not None:
            self._validate_server_interaction(
                tenant_id=tenant_id,
                local_interaction_id=event.local_interaction_id,
                server_interaction_id=server_interaction_id,
            )
        persisted_at = datetime.now(UTC)
        try:
            with self._session.begin_nested():
                RuntimeEvidenceLedger(self._session).append_fact(
                    event_id=event.event_id,
                    tenant_id=tenant_id,
                    mission_id=None,
                    category="ui_interaction",
                    action="browser_event",
                    producer="frontend.browser",
                    actor=actor_id,
                    details=f"Browser observed {event.phase} for {event.action_id}",
                    facts={"ui_interaction": _browser_fact(event)},
                    authority_context={"authority_class": "untrusted_observation", "grants_execution_authority": False},
                    causation_id=str(event.predecessor_event_id) if event.predecessor_event_id else None,
                    correlation_id=str(server_interaction_id),
                    occurred_at=persisted_at,
                )
        except IntegrityError:
            # A concurrent retry lost the primary-key race. The event is
            # immutable, so return the committed winner rather than writing a
            # second observation or exposing cross-tenant information.
            existing = self._audit.get_for_tenant(event_id=event.event_id, tenant_id=tenant_id)
            if existing is None:
                # The primary key is intentionally global.  Do not reveal
                # whether another tenant owns this browser-generated UUID;
                # simply refuse to associate it with this tenant's trace.
                raise UIInteractionTraceError("UI_INTERACTION_EVENT_ID_CONFLICT") from None
            fact = _read_ui_fact(existing)
            envelope = RuntimeEvidenceLedger.read_envelope(existing)
            if fact is None or envelope is None or envelope.correlation_id is None:
                raise UIInteractionTraceError("UI_INTERACTION_EVENT_ID_CONFLICT") from None
            return UIInteractionReceipt(
                event_id=event.event_id,
                server_interaction_id=uuid.UUID(envelope.correlation_id),
                persisted_at=existing.created_at,
                duplicate=True,
            )
        # This endpoint is the durable boundary.  Its acknowledgement is not
        # returned until the ledger transaction has committed.
        self._session.commit()
        return UIInteractionReceipt(
            event_id=event.event_id,
            server_interaction_id=server_interaction_id,
            persisted_at=persisted_at,
        )

    def resolve_server_interaction(
        self,
        *,
        tenant_id: str,
        local_interaction_id: uuid.UUID | None,
        server_interaction_id: uuid.UUID | None,
    ) -> uuid.UUID:
        if server_interaction_id is not None:
            if local_interaction_id is None:
                raise UIInteractionTraceError("UI_INTERACTION_LOCAL_ID_REQUIRED")
            self._validate_server_interaction(
                tenant_id=tenant_id,
                local_interaction_id=local_interaction_id,
                server_interaction_id=server_interaction_id,
            )
            return server_interaction_id
        if local_interaction_id is not None:
            event = self._audit.get_for_tenant(event_id=local_interaction_id, tenant_id=tenant_id)
            envelope = RuntimeEvidenceLedger.read_envelope(event) if event is not None else None
            fact = _read_ui_fact(event) if event is not None else None
            if (
                envelope is not None
                and fact is not None
                and fact.get("local_interaction_id") == str(local_interaction_id)
                and envelope.correlation_id
            ):
                return uuid.UUID(envelope.correlation_id)
        return uuid.uuid4()

    def append_server_event(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        interaction_id: uuid.UUID,
        local_interaction_id: uuid.UUID | None,
        action_id: str,
        phase: ServerPhase,
        outcome_code: str,
        causation_id: str | None = None,
    ) -> AuditEvent | None:
        """Persist a non-authoritative observation without blocking OAuth."""

        try:
            with self._session.begin_nested():
                return RuntimeEvidenceLedger(self._session).append_fact(
                    tenant_id=tenant_id,
                    mission_id=None,
                    category="ui_interaction",
                    action="server_event",
                    producer="api.provider_credentials",
                    actor=actor_id,
                    details=f"Server observed {phase} for {action_id}",
                    facts={
                        "ui_interaction": {
                            "schema_version": UI_INTERACTION_SCHEMA_VERSION,
                            "evidence_origin": "server_authoritative",
                            "server_interaction_id": str(interaction_id),
                            "local_interaction_id": str(local_interaction_id) if local_interaction_id else None,
                            "action_id": action_id,
                            "phase": phase,
                            "outcome_code": outcome_code,
                            "server_received_at": datetime.now(UTC).isoformat(),
                        }
                    },
                    authority_context={"authority_class": "observation", "grants_execution_authority": False},
                    causation_id=causation_id,
                    correlation_id=str(interaction_id),
                )
        except Exception:
            return None

    def _validate_server_interaction(
        self,
        *,
        tenant_id: str,
        local_interaction_id: uuid.UUID,
        server_interaction_id: uuid.UUID,
    ) -> None:
        event = self._audit.get_for_tenant(event_id=local_interaction_id, tenant_id=tenant_id)
        envelope = RuntimeEvidenceLedger.read_envelope(event) if event is not None else None
        fact = _read_ui_fact(event) if event is not None else None
        if (
            envelope is None
            or fact is None
            or fact.get("local_interaction_id") != str(local_interaction_id)
            or envelope.correlation_id != str(server_interaction_id)
        ):
            raise UIInteractionTraceError("UI_INTERACTION_ASSOCIATION_INVALID")
