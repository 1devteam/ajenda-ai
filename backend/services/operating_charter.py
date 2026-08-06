from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from backend.services.tools.schemas import SideEffectClass

CHARTER_CATEGORY = "operating_charter"
CHARTER_SCHEMA_VERSION = 1

ApprovalMode = Literal["notify_before_external", "always_notify", "none"]

DEFAULT_MAY_PREPARE: tuple[str, ...] = (
    "retrieval.hybrid_search",
    "record.search",
    "record.read",
    "web.research",
    "web.search",
    "web.page_read",
    "web.browser_session",
    "http.request",
    "sales.qualify",
    "sales.score_lead",
    "sales.recommend_next_action",
    "gtm.lead_enrich",
    "gtm.email_draft",
    "sales.draft_followup",
    "document.generate",
    "document.search",
    "document.read",
    "sales.research",
    "crm.research",
    "crm.read",
    "salesforce.soql_read",
    "provider.external_read",
    "linkedin.profile_read",
    "github.repo_read",
    "gtm.email_check",
    "google_calendar.events_read",
    "calendar.read",
)

DEFAULT_MAY_PERFORM: tuple[str, ...] = (
    "gtm.crm_upsert",
    "record.write",
    "sales.log_activity",
    "sales.create_followup_task",
    "calendar.create_event",
    "web.open_write",
)

DEFAULT_NEVER_DO: tuple[str, ...] = (
    "gtm.email_send",
    "gtm.social_publish",
    "webhook.dispatch",
)

DEFAULT_APPROVAL_MODE: ApprovalMode = "notify_before_external"


class OperatingCharterViolation(ValueError):
    """Raised when a launch violates the tenant operating charter."""

    def __init__(self, *, code: str, message: str, action: str) -> None:
        self.code = code
        self.message = message
        self.action = action
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class OperatingCharter:
    schema_version: int
    may_prepare: tuple[str, ...]
    may_perform: tuple[str, ...]
    never_do: tuple[str, ...]
    approval_mode: ApprovalMode
    escalation_email: str | None
    escalation_phone: str | None
    source: Literal["default", "profile"]

    def to_fact_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "may_prepare": list(self.may_prepare),
            "may_perform": list(self.may_perform),
            "never_do": list(self.never_do),
            "approval_mode": self.approval_mode,
        }
        if self.escalation_email:
            payload["escalation_email"] = self.escalation_email
        if self.escalation_phone:
            payload["escalation_phone"] = self.escalation_phone
        return payload


def default_operating_charter() -> OperatingCharter:
    return OperatingCharter(
        schema_version=CHARTER_SCHEMA_VERSION,
        may_prepare=DEFAULT_MAY_PREPARE,
        may_perform=DEFAULT_MAY_PERFORM,
        never_do=DEFAULT_NEVER_DO,
        approval_mode=DEFAULT_APPROVAL_MODE,
        escalation_email=None,
        escalation_phone=None,
        source="default",
    )
