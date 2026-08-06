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


def dogfood_operating_charter() -> OperatingCharter:
    """Profile charter that opts into governed external email send for M11 dogfood."""
    base = default_operating_charter()
    may_perform = tuple(sorted(set(base.may_perform) | {"gtm.email_send"}))
    never_do = tuple(item for item in base.never_do if item != "gtm.email_send")
    return OperatingCharter(
        schema_version=CHARTER_SCHEMA_VERSION,
        may_prepare=base.may_prepare,
        may_perform=may_perform,
        never_do=never_do,
        approval_mode=base.approval_mode,
        escalation_email=base.escalation_email,
        escalation_phone=base.escalation_phone,
        source="profile",
    )


def _normalize_action_list(raw: Any, *, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"operating_charter.{field} must be a list")
    return tuple(str(item).strip() for item in raw if isinstance(item, str) and item.strip())


def _resolve_action_list(
    payload: dict[str, Any],
    *,
    key: str,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    """Use defaults only when the key is absent; preserve explicit empty lists."""
    if key not in payload:
        return default
    return _normalize_action_list(payload.get(key), field=key)


def _charter_payload_from_fact(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    nested = raw.get("value")
    if isinstance(nested, dict):
        return nested
    return raw


def parse_operating_charter_fact(raw: Any) -> OperatingCharter | None:
    payload = _charter_payload_from_fact(raw)
    if payload is None:
        return None

    schema_version = payload.get("schema_version", CHARTER_SCHEMA_VERSION)
    try:
        parsed_schema_version = int(schema_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("operating_charter.schema_version must be an integer") from exc

    approval_mode = str(payload.get("approval_mode", DEFAULT_APPROVAL_MODE)).strip()
    if approval_mode not in {"notify_before_external", "always_notify", "none"}:
        raise ValueError("operating_charter.approval_mode is invalid")

    escalation_email = payload.get("escalation_email")
    escalation_phone = payload.get("escalation_phone")

    return OperatingCharter(
        schema_version=parsed_schema_version,
        may_prepare=_resolve_action_list(payload, key="may_prepare", default=DEFAULT_MAY_PREPARE),
        may_perform=_resolve_action_list(payload, key="may_perform", default=DEFAULT_MAY_PERFORM),
        never_do=_resolve_action_list(payload, key="never_do", default=DEFAULT_NEVER_DO),
        approval_mode=approval_mode,  # type: ignore[arg-type]
        escalation_email=str(escalation_email).strip()
        if isinstance(escalation_email, str) and escalation_email.strip()
        else None,
        escalation_phone=str(escalation_phone).strip()
        if isinstance(escalation_phone, str) and escalation_phone.strip()
        else None,
        source="profile",
    )


def load_operating_charter(*, approved_facts: dict[str, Any] | None) -> OperatingCharter:
    if not approved_facts:
        return default_operating_charter()
    try:
        parsed = parse_operating_charter_fact(approved_facts.get(CHARTER_CATEGORY))
    except ValueError:
        return default_operating_charter()
    return parsed if parsed is not None else default_operating_charter()


def _list_allows(action_name: str, allowed: tuple[str, ...]) -> bool:
    if "*" in allowed:
        return True
    return action_name in allowed


_EXTERNAL_PERFORM_SIDE_EFFECTS = frozenset(
    {
        SideEffectClass.EXTERNAL_SEND,
        SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.EXTERNAL_PUBLISH,
    }
)


def charter_requires_human_review_for_launch(
    *,
    charter: OperatingCharter,
    side_effect_class: SideEffectClass,
) -> bool:
    """Honor approval_mode for external perform launches (notify before side effects)."""
    if charter.approval_mode == "none":
        return False
    if side_effect_class not in _EXTERNAL_PERFORM_SIDE_EFFECTS:
        return False
    return charter.approval_mode in {"notify_before_external", "always_notify"}


def assert_action_allowed(
    *,
    action_name: str,
    side_effect_class: SideEffectClass,
    charter: OperatingCharter,
) -> None:
    if action_name in charter.never_do:
        raise OperatingCharterViolation(
            code="CHARTER_NEVER_DO",
            message=f"Action {action_name!r} is blocked by the tenant operating charter.",
            action=action_name,
        )

    if side_effect_class.has_side_effect:
        if not _list_allows(action_name, charter.may_perform):
            raise OperatingCharterViolation(
                code="CHARTER_PERFORM_NOT_ALLOWED",
                message=f"Action {action_name!r} requires perform permission in the operating charter.",
                action=action_name,
            )
        return

    if not _list_allows(action_name, charter.may_prepare):
        raise OperatingCharterViolation(
            code="CHARTER_PREPARE_NOT_ALLOWED",
            message=f"Action {action_name!r} requires prepare permission in the operating charter.",
            action=action_name,
        )
