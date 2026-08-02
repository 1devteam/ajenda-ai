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
    JobDependency,
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
    "research.discover_prospects": ("web.research", "sales.research", "web.search", "web.page_read", "crm.research"),
    "sales.research_context": ("sales.research", "crm.research", "web.research", "web.search"),
    "sales.qualify_prospects": ("sales.qualify", "sales.score_lead"),
    "gtm.enrich_contacts": ("gtm.lead_enrich",),
    "email.prepare_outreach": ("gtm.email_draft", "sales.draft_followup"),
    "email.deliver_outreach": ("gtm.email_send",),
    "email.read_messages": ("gtm.email_check",),
    "crm.read_records": ("sales.research",),
    "crm.query_salesforce": ("salesforce.soql_read",),
    "crm.pipeline_maintenance": ("gtm.crm_upsert",),
    "ops.calendar_briefing": ("google_calendar.events_read",),
    "gtm.publish_content": ("gtm.social_publish",),
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
    "gtm.social_publish": {
        "provider": "external_social",
        "integration": "linkedin",
        "credential_id": "linkedin-social",
    },
}

# Some hybrid actions are connector-bound only for a specific business job.
# Keeping this job-scoped preserves Ajenda-brain fallback for ordinary sales research.
_JOB_CONNECTION_HINTS: dict[tuple[str, str], dict[str, str]] = {
    ("crm.read_records", "sales.research"): {
        "provider": "external_crm",
        "integration": "hubspot",
        "credential_id": "hubspot-crm",
    },
}

_SOURCE_CONNECTION_HINTS: dict[tuple[str, str], dict[str, str]] = {
    # Applied only when the intent explicitly requires HubSpot as its source.
    ("research.discover_prospects", "sales.research"): {
        "provider": "external_crm",
        "integration": "hubspot",
        "credential_id": "hubspot-crm",
    },
    ("research.discover_prospects", "crm.research"): {
        "provider": "external_crm",
        "integration": "hubspot",
        "credential_id": "hubspot-crm",
    },
}


def intent_requires_hubspot_research_source(intent: MissionIntent) -> bool:
    """True when the user required HubSpot/CRM as the research source of truth."""

    if "hubspot_source" in {str(item) for item in intent.context_requirements}:
        return True
    for entity in intent.target_entities:
        attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
        if attrs.get("research_source") == "hubspot":
            return True
    return False


def _intent_input_sources(intent: MissionIntent) -> set[str]:
    """What structured inputs the intent already satisfies (no invented work)."""

    sources: set[str] = set()
    if intent.has_recipient_context():
        sources.update({"recipient_context", "explicit_recipient", "explicit_email"})
    for entity in intent.target_entities:
        # Industry/location market targeting is not a concrete prospect list.
        if entity.name and entity.type in {"company", "person", "contact", "recipient"}:
            sources.add("named_company")
            sources.add("explicit_company")
        if entity.industry or entity.location:
            sources.add("market_scope")
        if entity.email:
            sources.add("explicit_email")
            sources.add("recipient_context")
        if (entity.attributes or {}).get("crm_record_id"):
            sources.add("crm_record")
        if entity.domain or entity.url:
            sources.add("explicit_company")
            sources.add("named_company")
    if intent.requested_quantity is not None:
        sources.add("quantity")
    # Standalone publish copy is available unless the instruction says "post the results".
    if "publish_content" in {str(o) for o in intent.requested_outcomes}:
        result_based = any(
            isinstance(entity.attributes, dict) and entity.attributes.get("publish_result_based")
            for entity in intent.target_entities
        )
        if not result_based:
            sources.add("standalone_publish_content")
            sources.add("publish_payload")
    return sources


def _dependency_should_expand(dep: JobDependency, *, available: set[str]) -> bool:
    if dep.kind == "optional":
        return False
    if dep.kind == "hard":
        return True
    if dep.satisfied_by and any(item in available for item in dep.satisfied_by):
        return False
    if not dep.required_when_missing:
        return False
    return any(item not in available for item in dep.required_when_missing)


def route_jobs_for_intent(intent: MissionIntent) -> list[BusinessJob]:
    """Map canonical requested outcomes to business jobs (deterministic)."""

    outcomes = {item.strip() for item in intent.requested_outcomes if item and item.strip()}
    if not outcomes:
        return []

    selected: list[BusinessJob] = []
    selected_keys: set[str] = set()
    available = _intent_input_sources(intent)

    for job in list_business_jobs():
        supported = set(job.supported_outcomes)
        if outcomes.intersection(supported):
            if job.job_key not in selected_keys:
                selected.append(job)
                selected_keys.add(job.job_key)

    expanded = list(selected)
    pending = list(selected)
    while pending:
        job = pending.pop()
        deps: list[JobDependency] = list(job.dependencies)
        if not deps:
            deps = [JobDependency(job_key=k, kind="hard") for k in job.depends_on_jobs]
        for dep in deps:
            if dep.job_key in selected_keys:
                continue
            if not _dependency_should_expand(dep, available=available):
                continue
            dep_job = BUSINESS_JOBS_BY_KEY.get(dep.job_key)
            if dep_job is None:
                continue
            expanded.append(dep_job)
            selected_keys.add(dep.job_key)
            pending.append(dep_job)

    catalog_order = {job.job_key: index for index, job in enumerate(list_business_jobs())}
    expanded.sort(key=lambda job: catalog_order.get(job.job_key, 999))

    if intent.send_policy.mode != "allow" or intent.blocks_send():
        expanded = [job for job in expanded if job.job_key != "email.deliver_outreach"]
    if "publish_content" not in outcomes:
        expanded = [job for job in expanded if job.job_key != "gtm.publish_content"]

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
    job_key: str,
    connected_credential_ids: set[str],
    connected_integrations: set[str],
    preferred_credential_by_integration: dict[str, tuple[str, str]] | None = None,
    credential_type_by_id: dict[str, str] | None = None,
    source_connection_required: bool = False,
) -> tuple[bool, dict[str, str] | None, str | None, str | None]:
    """Return (connected, catalog_hint, matched_credential_id, matched_credential_type)."""

    preferred_credential_by_integration = preferred_credential_by_integration or {}
    credential_type_by_id = credential_type_by_id or {}
    source_hint = _SOURCE_CONNECTION_HINTS.get((job_key, action_name)) if source_connection_required else None
    hint = source_hint or _JOB_CONNECTION_HINTS.get((job_key, action_name)) or _CONNECTION_HINTS.get(action_name)
    if hint is None:
        return True, None, None, None
    if hint["credential_id"] in connected_credential_ids:
        cred_type = credential_type_by_id.get(hint["credential_id"], "api_key")
        return True, hint, hint["credential_id"], cred_type
    if hint["integration"] in connected_integrations:
        matched = preferred_credential_by_integration.get(hint["integration"])
        if matched is None:
            return True, hint, None, None
        matched_id, matched_type = matched
        return True, hint, matched_id, matched_type
    return False, hint, None, None


def evaluate_action_candidate(
    *,
    job: BusinessJob,
    action_name: str,
    charter: OperatingCharter,
    connected_credential_ids: set[str],
    connected_integrations: set[str],
    forbid_actions: set[str],
    preferred_credential_by_integration: dict[str, tuple[str, str]] | None = None,
    credential_type_by_id: dict[str, str] | None = None,
    require_connection: bool = False,
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

    connected, hint, matched_credential_id, matched_credential_type = _connection_status(
        action_name,
        job_key=job.job_key,
        connected_credential_ids=connected_credential_ids,
        connected_integrations=connected_integrations,
        preferred_credential_by_integration=preferred_credential_by_integration,
        credential_type_by_id=credential_type_by_id,
        source_connection_required=require_connection,
    )
    # Any action with a connection hint is fail-closed without that connection.
    # Optional job policy must not make external-hinted actions "ready" then simulate.
    force_hint_connection = hint is not None
    connection_required = (
        job.credential_policy == "required"
        or force_hint_connection
        or (require_connection and action_name in {"sales.research", "crm.research"})
    )
    if connection_required and not connected:
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
            connection_provider=(hint["integration"] if hint else None) or "required_connection",
        )

    credential_reference = None
    if hint and connected and matched_credential_id:
        credential_reference = {
            "schema_version": 1,
            "credential_id": matched_credential_id,
            "provider": hint["provider"],
            "credential_type": matched_credential_type or "api_key",
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
    preferred_credential_by_integration: dict[str, tuple[str, str]] | None = None,
    credential_type_by_id: dict[str, str] | None = None,
) -> tuple[list[AbilitySelection], list[dict[str, Any]]]:
    """Select one primary ability per job and collect missing connections."""

    charter = charter or default_operating_charter()
    connected_credential_ids = connected_credential_ids or set()
    connected_integrations = connected_integrations or set()
    preferred_credential_by_integration = preferred_credential_by_integration or {}
    credential_type_by_id = credential_type_by_id or {}
    forbid_actions = {item.strip() for item in intent.forbidden_outcomes if item.strip()}
    # Structured send policy is authoritative (do not reparse constraint prose).
    if intent.send_policy.mode in {"forbid", "conditional"} or intent.blocks_send():
        forbid_actions.add("gtm.email_send")
    if "gtm.email_send" in forbid_actions or "send messages" in forbid_actions:
        forbid_actions.add("gtm.email_send")

    selections: list[AbilitySelection] = []
    missing: list[dict[str, Any]] = []

    hubspot_source = intent_requires_hubspot_research_source(intent)

    for job in jobs:
        preference = list(_ACTION_PREFERENCE.get(job.job_key, job.candidate_actions))
        # Explicit CRM source: only connector-bound research actions (never public web first).
        if hubspot_source and job.job_key == "research.discover_prospects":
            preference = ["sales.research", "crm.research"]
            ordered = preference
            require_connection = True
        else:
            ordered = preference + [a for a in job.candidate_actions if a not in preference]
            require_connection = False
        evaluated = [
            evaluate_action_candidate(
                job=job,
                action_name=action_name,
                charter=charter,
                connected_credential_ids=connected_credential_ids,
                connected_integrations=connected_integrations,
                forbid_actions=forbid_actions,
                preferred_credential_by_integration=preferred_credential_by_integration,
                credential_type_by_id=credential_type_by_id,
                require_connection=require_connection,
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
