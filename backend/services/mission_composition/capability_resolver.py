"""Resolve business jobs to governed abilities with readiness.

Deterministic selection only. Never queues work or grants runtime authority.
"""

from __future__ import annotations

from typing import Any

from backend.services.abilities.catalog import ABILITY_MANIFESTS_BY_ACTION
from backend.services.mission_composition.contracts import (
    CAPABILITY_RESOLVER_VERSION,
    AbilityAlternative,
    AbilitySelection,
    BusinessJob,
    MissionIntent,
)
from backend.services.mission_composition.job_catalog import BUSINESS_JOBS_BY_KEY, list_business_jobs
from backend.services.operating_charter import (
    OperatingCharter,
    OperatingCharterViolation,
    assert_action_allowed,
    default_operating_charter,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import SideEffectClass

# Preferred order when multiple candidates are ready.
_ACTION_PREFERENCE: dict[str, tuple[str, ...]] = {
    "research.discover_prospects": ("web.research", "sales.research", "web.search", "crm.research"),
    "sales.research_context": ("sales.research", "crm.research", "web.research"),
    "sales.qualify_prospects": ("sales.qualify", "sales.score_lead"),
    "gtm.enrich_contacts": ("gtm.lead_enrich",),
    "email.prepare_outreach": ("gtm.email_draft", "sales.draft_followup"),
    "email.deliver_outreach": ("gtm.email_send",),
    "crm.pipeline_maintenance": ("gtm.crm_upsert", "sales.log_activity", "record.write"),
    "ops.calendar_briefing": ("google_calendar.events_read", "calendar.read"),
}

_CONNECTION_HINTS: dict[str, dict[str, str]] = {
    "crm.research": {
        "provider": "external_crm",
        "integration": "hubspot",
        "credential_id": "hubspot-crm",
    },
    "gtm.crm_upsert": {
        "provider": "external_crm",
        "integration": "hubspot",
        "credential_id": "hubspot-crm",
    },
    "gtm.email_send": {
        "provider": "external_email",
        "integration": "gmail",
        "credential_id": "gmail-email",
    },
    "gtm.email_check": {
        "provider": "external_email",
        "integration": "gmail",
        "credential_id": "gmail-email",
    },
    "google_calendar.events_read": {
        "provider": "external_read_provider",
        "integration": "google_calendar",
        "credential_id": "google-calendar-read",
    },
    "salesforce.soql_read": {
        "provider": "external_read_provider",
        "integration": "salesforce",
        "credential_id": "salesforce-read",
    },
}


def _normalize_outcome(value: str) -> str:
    return " ".join(value.lower().split())


def route_jobs_for_intent(intent: MissionIntent) -> list[BusinessJob]:
    """Map requested outcomes to business jobs (deterministic)."""

    outcomes = {_normalize_outcome(item) for item in intent.requested_outcomes}
    if not outcomes:
        return []

    selected: list[BusinessJob] = []
    selected_keys: set[str] = set()

    for job in list_business_jobs():
        supported = {_normalize_outcome(item) for item in job.supported_outcomes}
        if outcomes.intersection(supported):
            if job.job_key not in selected_keys:
                selected.append(job)
                selected_keys.add(job.job_key)

    # Expand required upstream dependencies transitively (fixed-point).
    expanded = list(selected)
    pending = list(selected)
    while pending:
        job = pending.pop()
        for dep_key in job.depends_on_jobs:
            if dep_key in selected_keys:
                continue
            dep = BUSINESS_JOBS_BY_KEY.get(dep_key)
            if dep is None:
                continue
            expanded.append(dep)
            selected_keys.add(dep_key)
            pending.append(dep)

    # Stable topological-ish order: dependencies first by catalog order.
    catalog_order = {job.job_key: index for index, job in enumerate(list_business_jobs())}
    expanded.sort(key=lambda job: catalog_order.get(job.job_key, 999))

    # Drop explicit send job when intent forbids send.
    forbidden = {_normalize_outcome(item) for item in intent.forbidden_outcomes}
    constraints = {_normalize_outcome(item) for item in intent.constraints}
    block_send = (
        "gtm.email_send" in forbidden
        or "send messages" in forbidden
        or any("do not send" in item for item in constraints)
        or any("before anything is sent" in item for item in constraints)
    )
    if block_send:
        expanded = [job for job in expanded if job.job_key != "email.deliver_outreach"]

    return expanded


def _side_effect_for_action(action_name: str) -> SideEffectClass:
    registry = get_default_action_registry()
    try:
        definition = registry.get(action_name)
    except ValueError:
        return SideEffectClass.NONE
    return definition.side_effect_class


def _charter_allows(*, action_name: str, charter: OperatingCharter) -> tuple[bool, str | None]:
    side_effect = _side_effect_for_action(action_name)
    try:
        assert_action_allowed(action_name=action_name, side_effect_class=side_effect, charter=charter)
    except OperatingCharterViolation as exc:
        return False, exc.message
    return True, None


def _connection_status(
    action_name: str,
    *,
    connected_credential_ids: set[str],
    connected_integrations: set[str],
    preferred_credential_by_integration: dict[str, str] | None = None,
) -> tuple[bool, dict[str, str] | None, str | None]:
    """Return (connected, catalog_hint, matched_credential_id)."""

    preferred_credential_by_integration = preferred_credential_by_integration or {}
    hint = _CONNECTION_HINTS.get(action_name)
    if hint is None:
        return True, None, None
    if hint["credential_id"] in connected_credential_ids:
        return True, hint, hint["credential_id"]
    if hint["integration"] in connected_integrations:
        matched = preferred_credential_by_integration.get(hint["integration"])
        return True, hint, matched
    return False, hint, None


def evaluate_action_candidate(
    *,
    job: BusinessJob,
    action_name: str,
    charter: OperatingCharter,
    connected_credential_ids: set[str],
    connected_integrations: set[str],
    forbid_actions: set[str],
    preferred_credential_by_integration: dict[str, str] | None = None,
) -> AbilitySelection:
    registry = get_default_action_registry()
    manifest = ABILITY_MANIFESTS_BY_ACTION.get(action_name)
    side_effect = _side_effect_for_action(action_name)

    if action_name in forbid_actions or action_name in set(charter.never_do):
        return AbilitySelection(
            job_key=job.job_key,
            ability_id=manifest.ability_id if manifest else None,
            action_name=action_name,
            selection_status="rejected",
            selection_reason="Blocked by mission forbidden_actions or operating charter never_do.",
            readiness="charter_blocked",
            vertical_role=job.vertical_role,
            side_effect_class=side_effect.value,
        )

    if job.maturity == "catalog_only":
        return AbilitySelection(
            job_key=job.job_key,
            ability_id=manifest.ability_id if manifest else None,
            action_name=action_name,
            selection_status="rejected",
            selection_reason="Job maturity is catalog_only; cannot enter runtime graphs.",
            readiness="catalog_only",
            vertical_role=job.vertical_role,
            side_effect_class=side_effect.value,
        )

    try:
        registry.get(action_name)
        registered = True
    except ValueError:
        registered = False

    if not registered:
        return AbilitySelection(
            job_key=job.job_key,
            ability_id=manifest.ability_id if manifest else None,
            action_name=action_name,
            selection_status="rejected",
            selection_reason="Action is not registered in the ActionRegistry.",
            readiness="unavailable",
            vertical_role=job.vertical_role,
            side_effect_class=side_effect.value,
        )

    if manifest is None:
        return AbilitySelection(
            job_key=job.job_key,
            ability_id=None,
            action_name=action_name,
            selection_status="rejected",
            selection_reason="Action lacks a valid ability manifest.",
            readiness="unavailable",
            vertical_role=job.vertical_role,
            side_effect_class=side_effect.value,
        )

    allowed, charter_message = _charter_allows(action_name=action_name, charter=charter)
    if not allowed:
        return AbilitySelection(
            job_key=job.job_key,
            ability_id=manifest.ability_id,
            action_name=action_name,
            selection_status="rejected",
            selection_reason=charter_message or "Blocked by operating charter.",
            readiness="charter_blocked",
            vertical_role=job.vertical_role,
            side_effect_class=side_effect.value,
        )

    connected, hint, matched_credential_id = _connection_status(
        action_name,
        connected_credential_ids=connected_credential_ids,
        connected_integrations=connected_integrations,
        preferred_credential_by_integration=preferred_credential_by_integration,
    )
    if job.credential_policy == "required" and not connected:
        return AbilitySelection(
            job_key=job.job_key,
            ability_id=manifest.ability_id,
            action_name=action_name,
            selection_status="rejected",
            selection_reason="Required connection is missing; will not simulate provider success.",
            readiness="connection_required",
            vertical_role=job.vertical_role,
            side_effect_class=side_effect.value,
            requires_connection=True,
            connection_provider=hint["integration"] if hint else None,
        )

    if not connected and hint is not None and action_name in {"crm.research"}:
        # Prefer internal/public alternatives; mark this as alternative.
        return AbilitySelection(
            job_key=job.job_key,
            ability_id=manifest.ability_id,
            action_name=action_name,
            selection_status="alternative",
            selection_reason="External CRM connection missing; usable only after connect.",
            readiness="connection_required",
            vertical_role=job.vertical_role,
            side_effect_class=side_effect.value,
            requires_connection=True,
            connection_provider=hint["integration"],
        )

    credential_reference = None
    if hint and connected and matched_credential_id:
        credential_reference = {
            "schema_version": 1,
            "credential_id": matched_credential_id,
            "provider": hint["provider"],
            "credential_type": "api_key",
        }

    return AbilitySelection(
        job_key=job.job_key,
        ability_id=manifest.ability_id,
        action_name=action_name,
        selection_status="selected",
        selection_reason="Registered, charter-allowed, runtime-bound ability for this job.",
        readiness="ready",
        vertical_role=job.vertical_role,
        side_effect_class=side_effect.value,
        requires_connection=bool(hint),
        connection_provider=hint["integration"] if hint else None,
        credential_reference=credential_reference,
    )


def resolve_jobs(
    jobs: list[BusinessJob],
    *,
    intent: MissionIntent,
    charter: OperatingCharter | None = None,
    connected_credential_ids: set[str] | None = None,
    connected_integrations: set[str] | None = None,
    preferred_credential_by_integration: dict[str, str] | None = None,
) -> tuple[list[AbilitySelection], list[dict[str, Any]]]:
    """Select one primary ability per job and collect missing connections."""

    charter = charter or default_operating_charter()
    connected_credential_ids = connected_credential_ids or set()
    connected_integrations = connected_integrations or set()
    preferred_credential_by_integration = preferred_credential_by_integration or {}
    forbid_actions = {item.strip() for item in intent.forbidden_outcomes if item.strip()}
    # Treat gtm.email_send as forbidden when "send messages" constraint present.
    if any("do not send" in c.lower() for c in intent.constraints):
        forbid_actions.add("gtm.email_send")
    if "gtm.email_send" in forbid_actions or "send messages" in forbid_actions:
        forbid_actions.add("gtm.email_send")

    selections: list[AbilitySelection] = []
    missing: list[dict[str, Any]] = []

    for job in jobs:
        preference = _ACTION_PREFERENCE.get(job.job_key, job.candidate_actions)
        ordered = list(preference) + [a for a in job.candidate_actions if a not in preference]
        evaluated = [
            evaluate_action_candidate(
                job=job,
                action_name=action_name,
                charter=charter,
                connected_credential_ids=connected_credential_ids,
                connected_integrations=connected_integrations,
                forbid_actions=forbid_actions,
                preferred_credential_by_integration=preferred_credential_by_integration,
            )
            for action_name in ordered
        ]

        ready = [
            candidate
            for candidate in evaluated
            if candidate.readiness == "ready" and candidate.selection_status == "selected"
        ]
        if ready:
            primary = ready[0]
            alternatives = [
                AbilityAlternative(
                    action=candidate.action_name,
                    status=candidate.readiness,
                    reason_not_selected=candidate.selection_reason,
                )
                for candidate in evaluated
                if candidate.action_name != primary.action_name
            ]
            selections.append(primary.model_copy(update={"alternatives": alternatives}))
            continue

        # No ready selection: keep best rejected/connection_required for reporting.
        if not evaluated:
            continue
        fallback = evaluated[0]
        alternatives = [
            AbilityAlternative(
                action=candidate.action_name,
                status=candidate.readiness,
                reason_not_selected=candidate.selection_reason,
            )
            for candidate in evaluated[1:]
        ]
        fallback = fallback.model_copy(
            update={
                "selection_status": "rejected",
                "alternatives": alternatives,
            }
        )
        selections.append(fallback)
        for candidate in evaluated:
            if candidate.readiness == "connection_required" and candidate.connection_provider:
                missing.append(
                    {
                        "job_key": job.job_key,
                        "action": candidate.action_name,
                        "provider": candidate.connection_provider,
                        "status": "connection_required",
                        "message": candidate.selection_reason,
                    }
                )

    # Dedupe missing connections
    seen: set[tuple[str, str]] = set()
    unique_missing: list[dict[str, Any]] = []
    for entry in missing:
        key = (str(entry.get("provider")), str(entry.get("action")))
        if key in seen:
            continue
        seen.add(key)
        unique_missing.append(entry)

    return selections, unique_missing


def resolver_version() -> str:
    return CAPABILITY_RESOLVER_VERSION
