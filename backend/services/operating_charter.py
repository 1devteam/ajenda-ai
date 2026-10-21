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
    "research.observe_contacts",
    "research.verify_public_candidates",
    "research.verify_public_identity",
    "research.synthesize_report",
    "knowledge.retrieve_current",
    "decision.recommend_next_action",
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
    "crm.observe",
    "crm.reconcile",
    "crm.verify_effect",
    "salesforce.soql_read",
    "provider.external_read",
    "linkedin.profile_read",
    "github.repo_read",
    "gtm.email_check",
    "google_calendar.events_read",
    "calendar.read",
    "vertical.finance.sync_revenue",
    "vertical.finance.prepare_reconciliation",
    "vertical.finance.prepare_invoice_drafts",
    "runtime.verify_controls",
    "analysis.evaluate_goal_progress",
)

DEFAULT_MAY_PERFORM: tuple[str, ...] = (
    "gtm.crm_upsert",
    "record.write",
    "sales.log_activity",
    "sales.create_followup_task",
    "calendar.create_event",
    "web.open_write",
    "crm.mutate",
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


class OperatingCharterConfigurationError(OperatingCharterViolation):
    """Raised when the active tenant has no valid persisted charter.

    A runtime policy decision must never inherit authority from the editor
    defaults.  Callers already handle :class:`OperatingCharterViolation`, so
    keeping this as a subclass preserves the fail-closed response path while
    making configuration failures distinguishable from a denied action.
    """

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(code=code, message=message, action=CHARTER_CATEGORY)


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
    revision: int = 0

    def to_fact_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "may_prepare": list(self.may_prepare),
            "may_perform": list(self.may_perform),
            "never_do": list(self.never_do),
            "approval_mode": self.approval_mode,
            "revision": self.revision,
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
        revision=0,
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
        revision=0,
    )


def _normalize_action_list(raw: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"operating_charter.{field} must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ValueError(f"operating_charter.{field} entries must be non-empty strings")
    normalized = tuple(item.strip() for item in raw)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"operating_charter.{field} entries must be unique")
    return normalized


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

    required_fields = ("schema_version", "may_prepare", "may_perform", "never_do", "approval_mode")
    missing_fields = [field for field in required_fields if field not in payload]
    if missing_fields:
        raise ValueError(f"operating_charter is missing required fields: {', '.join(missing_fields)}")

    schema_version = payload["schema_version"]
    try:
        parsed_schema_version = int(schema_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("operating_charter.schema_version must be an integer") from exc
    if parsed_schema_version != CHARTER_SCHEMA_VERSION:
        raise ValueError(f"operating_charter.schema_version {parsed_schema_version} is not supported")

    raw_revision = payload.get("revision", 0)
    if isinstance(raw_revision, bool):
        raise ValueError("operating_charter.revision must be a non-negative integer")
    try:
        revision = int(raw_revision)
    except (TypeError, ValueError) as exc:
        raise ValueError("operating_charter.revision must be a non-negative integer") from exc
    if revision < 0:
        raise ValueError("operating_charter.revision must be a non-negative integer")

    approval_mode = str(payload.get("approval_mode", DEFAULT_APPROVAL_MODE)).strip()
    if approval_mode not in {"notify_before_external", "always_notify", "none"}:
        raise ValueError("operating_charter.approval_mode is invalid")

    escalation_email = payload.get("escalation_email")
    escalation_phone = payload.get("escalation_phone")

    may_prepare = _normalize_action_list(payload["may_prepare"], field="may_prepare")
    may_perform = _normalize_action_list(payload["may_perform"], field="may_perform")
    never_do = _normalize_action_list(payload["never_do"], field="never_do")
    _validate_action_sets(may_prepare=may_prepare, may_perform=may_perform, never_do=never_do)

    return OperatingCharter(
        schema_version=parsed_schema_version,
        may_prepare=may_prepare,
        may_perform=may_perform,
        never_do=never_do,
        approval_mode=approval_mode,  # type: ignore[arg-type]
        escalation_email=str(escalation_email).strip()
        if isinstance(escalation_email, str) and escalation_email.strip()
        else None,
        escalation_phone=str(escalation_phone).strip()
        if isinstance(escalation_phone, str) and escalation_phone.strip()
        else None,
        source="profile",
        revision=revision,
    )


def _validate_action_sets(
    *,
    may_prepare: tuple[str, ...],
    may_perform: tuple[str, ...],
    never_do: tuple[str, ...],
) -> None:
    supported_actions = frozenset(DEFAULT_MAY_PREPARE) | frozenset(DEFAULT_MAY_PERFORM) | frozenset(DEFAULT_NEVER_DO)
    supplied_actions = frozenset(may_prepare) | frozenset(may_perform) | frozenset(never_do)
    unknown_actions = sorted(supplied_actions - supported_actions)
    if unknown_actions:
        raise ValueError(f"operating_charter contains unsupported actions: {', '.join(unknown_actions)}")
    conflicting = sorted((frozenset(may_prepare) | frozenset(may_perform)) & frozenset(never_do))
    if conflicting:
        raise ValueError("operating_charter actions cannot be both allowed and never_do: " + ", ".join(conflicting))
    dual_authority = sorted(frozenset(may_prepare) & frozenset(may_perform))
    if dual_authority:
        raise ValueError(
            "operating_charter actions cannot be both may_prepare and may_perform: " + ", ".join(dual_authority)
        )


@dataclass(frozen=True, slots=True)
class OperatingCharterState:
    """Read model for the persisted charter, without editor-default fallback."""

    status: Literal["active", "missing", "invalid"]
    charter: OperatingCharter | None
    revision: int
    error_code: str | None = None
    error_message: str | None = None


def inspect_operating_charter(*, approved_facts: dict[str, Any] | None) -> OperatingCharterState:
    if not approved_facts or CHARTER_CATEGORY not in approved_facts:
        return OperatingCharterState(status="missing", charter=None, revision=0)
    raw = approved_facts.get(CHARTER_CATEGORY)
    try:
        charter = parse_operating_charter_fact(raw)
    except ValueError as exc:
        payload = _charter_payload_from_fact(raw)
        raw_revision = payload.get("revision", 0) if payload is not None else 0
        revision = (
            raw_revision
            if isinstance(raw_revision, int) and not isinstance(raw_revision, bool) and raw_revision >= 0
            else 0
        )
        return OperatingCharterState(
            status="invalid",
            charter=None,
            revision=revision,
            error_code="CHARTER_INVALID",
            error_message=str(exc),
        )
    if charter is None:
        return OperatingCharterState(
            status="invalid",
            charter=None,
            revision=0,
            error_code="CHARTER_INVALID",
            error_message="operating_charter must be an object",
        )
    return OperatingCharterState(status="active", charter=charter, revision=charter.revision)


def load_operating_charter(*, approved_facts: dict[str, Any] | None) -> OperatingCharter:
    state = inspect_operating_charter(approved_facts=approved_facts)
    if state.charter is not None:
        return state.charter
    if state.status == "missing":
        raise OperatingCharterConfigurationError(
            code="CHARTER_MISSING",
            message="No persisted operating charter is configured for this tenant.",
        )
    raise OperatingCharterConfigurationError(
        code=state.error_code or "CHARTER_INVALID",
        message=state.error_message or "The persisted operating charter is invalid.",
    )


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
