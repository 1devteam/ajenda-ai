"""Declarative connector capability schema for composition / restatement.

This catalog states what each product connector can do *when connected and
charter-allowed*. It does not perform OAuth, grant credentials, or execute
actions. Interpreter and readiness messaging use it to distinguish:

- unknown language (vocabulary miss)
- understood intent but connector/op not runtime-bound
- understood intent that needs a connection

Runtime still enforces registry, charter, and credential resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ConnectorOp = Literal["read", "write", "send", "publish", "list"]
ConnectorMaturity = Literal["runtime_bound", "partial", "catalog_only"]


@dataclass(frozen=True, slots=True)
class ConnectorCapability:
    """One product connector's declared operations and runtime wiring."""

    connector_id: str
    display_name: str
    provider: str
    operations: frozenset[str]
    # Ops that are product-requested but not fully runtime-bound yet.
    deferred_operations: frozenset[str]
    oauth_scopes: tuple[str, ...]
    runtime_actions: tuple[str, ...]
    maturity: ConnectorMaturity
    notes: str = ""


CONNECTOR_CAPABILITIES: tuple[ConnectorCapability, ...] = (
    ConnectorCapability(
        connector_id="gmail",
        display_name="Gmail",
        provider="external_email",
        operations=frozenset({"read", "send"}),
        deferred_operations=frozenset(),
        oauth_scopes=(
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ),
        runtime_actions=("gtm.email_send", "gtm.email_check"),
        maturity="runtime_bound",
        notes="Read and send require a live Gmail connection; send also requires explicit mission send policy and charter authority.",
    ),
    ConnectorCapability(
        connector_id="google_calendar",
        display_name="Google Calendar",
        provider="external_read_provider",
        operations=frozenset({"read"}),
        # OAuth may request events write scopes; composition runtime path is read today.
        deferred_operations=frozenset({"write"}),
        oauth_scopes=("https://www.googleapis.com/auth/calendar.events",),
        runtime_actions=("google_calendar.events_read", "calendar.read"),
        maturity="partial",
        notes=(
            "Calendar OAuth may include events write permission, but mission composition "
            "only schedules google_calendar.events_read. Create/update/delete stays fail-closed."
        ),
    ),
    ConnectorCapability(
        connector_id="google_contacts",
        display_name="Google Contacts",
        provider="external_read_provider",
        operations=frozenset({"read"}),
        deferred_operations=frozenset({"write"}),
        oauth_scopes=(
            "https://www.googleapis.com/auth/contacts",
            "https://www.googleapis.com/auth/contacts.other.readonly",
        ),
        # Runtime path is provider.external_read only today; write is not Contacts-bound
        # (gtm.crm_upsert resolves through HubSpot, not Google Contacts).
        runtime_actions=("provider.external_read",),
        maturity="partial",
        notes=(
            "Google Contacts is read-only in composition. Writes stay deferred until a "
            "Contacts write adapter is runtime-bound; do not advertise HubSpot upsert as Contacts write."
        ),
    ),
    ConnectorCapability(
        connector_id="linkedin",
        display_name="LinkedIn",
        provider="external_read_provider",
        operations=frozenset({"read"}),
        deferred_operations=frozenset({"publish"}),
        oauth_scopes=("openid", "profile", "email"),
        runtime_actions=("linkedin.profile_read", "gtm.social_publish"),
        maturity="partial",
        notes=(
            "Default OAuth is openid/profile/email. Member publish (w_member_social) is not "
            "default; gtm.social_publish is generic external_social and may simulate without creds."
        ),
    ),
    ConnectorCapability(
        connector_id="hubspot",
        display_name="HubSpot",
        provider="external_crm",
        operations=frozenset({"read", "write"}),
        deferred_operations=frozenset(),
        oauth_scopes=(),
        runtime_actions=("gtm.crm_upsert", "sales.research"),
        maturity="runtime_bound",
        notes="HubSpot reads use the sales.research runtime action with an external CRM credential reference.",
    ),
    ConnectorCapability(
        connector_id="salesforce",
        display_name="Salesforce",
        provider="external_read_provider",
        operations=frozenset({"read"}),
        deferred_operations=frozenset({"write"}),
        oauth_scopes=("api", "refresh_token"),
        runtime_actions=("salesforce.soql_read",),
        maturity="partial",
    ),
)

CONNECTORS_BY_ID: dict[str, ConnectorCapability] = {c.connector_id: c for c in CONNECTOR_CAPABILITIES}


def get_connector(connector_id: str) -> ConnectorCapability | None:
    return CONNECTORS_BY_ID.get(connector_id)


def connector_supports_op(connector_id: str, op: str) -> bool:
    cap = CONNECTORS_BY_ID.get(connector_id)
    return cap is not None and op in cap.operations


def connector_defers_op(connector_id: str, op: str) -> bool:
    cap = CONNECTORS_BY_ID.get(connector_id)
    return cap is not None and op in cap.deferred_operations


def restatement_for_deferred_op(*, connector_id: str, op: str) -> str | None:
    """Human restatement when intent is understood but op is not runtime-bound."""

    cap = CONNECTORS_BY_ID.get(connector_id)
    if cap is None or op not in cap.deferred_operations:
        return None
    available = ", ".join(sorted(cap.operations)) or "none"
    return (
        f"{cap.display_name} {op} was understood, but Ajenda only runs runtime-bound "
        f"operations for this connector today ({available}). "
        f"{cap.notes}".strip()
    )
