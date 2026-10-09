from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException, status

from backend.domain.mission import MISSION_INTAKE_METADATA_KEY, Mission
from backend.services.tools.action_registry import ActionDefinition, get_default_action_registry
from backend.services.tools.schemas import SideEffectClass

READ_SAFE_ACTIONS: set[str] = {
    "calendar.read",
    "sales.research",
    "sales.qualify",
    "sales.score_lead",
    "sales.recommend_next_action",
    "sales.draft_followup",
    "record.search",
    "record.read",
    # PR9: expose GTM low-risk (no side effect) for pilot under ability-runtime
    "gtm.lead_enrich",
    "gtm.email_draft",
    "retrieval.hybrid_search",
    "web.research",
    "web.search",
    "web.page_read",
    "research.observe_contacts",
    "knowledge.retrieve_current",
    "decision.recommend_next_action",
    "web.browser_session",
    "crm.research",
    "crm.read",
}

INTERNAL_WRITE_ACTIONS: set[str] = {
    "calendar.create_event",
    "record.write",
    "sales.log_activity",
    "sales.create_followup_task",
}

EXTERNAL_ACTIONS: set[str] = {
    "http.request",
    "web.open_write",
    "provider.external_read",
    "linkedin.profile_read",
    "salesforce.soql_read",
    "google_calendar.events_read",
    "github.repo_read",
    "webhook.dispatch",
    # PR9 pilot: high-risk GTM external side-effect actions (EXTERNAL_SEND/WRITE/PUBLISH)
    "gtm.email_send",
    "gtm.crm_upsert",
    "gtm.social_publish",
    # Gmail check (read)
    "gtm.email_check",
}

GTM_HIGH_RISK_ACTIONS: set[str] = {
    "gtm.email_send",
    "gtm.crm_upsert",
    "gtm.social_publish",
}

GTM_HIGH_RISK_ACTIONS_REQUIRING_CREDENTIAL: set[str] = {
    "gtm.email_send",
    "gtm.social_publish",
}

# Credentialed external reads require guardian approval before launch.
CREDENTIALED_EXTERNAL_READ_ACTIONS: set[str] = {
    "gtm.email_check",
    "sales.research",
    "crm.research",
    "crm.read",
    "linkedin.profile_read",
    "salesforce.soql_read",
    "google_calendar.events_read",
    "github.repo_read",
}

EXPOSED_ACTIONS: set[str] = READ_SAFE_ACTIONS | INTERNAL_WRITE_ACTIONS | EXTERNAL_ACTIONS

def _label_for_action(action_name: str) -> str:
    return action_name.replace(".", " ").replace("_", " ").title()

def _mission_allowed_actions(metadata_json: dict[str, Any]) -> list[str]:
    intake = metadata_json.get(MISSION_INTAKE_METADATA_KEY)
    if not isinstance(intake, dict):
        return []
    raw_actions = intake.get("allowed_actions")
    if not isinstance(raw_actions, list):
        return []
    return [str(item).strip() for item in raw_actions if isinstance(item, str) and item.strip()]

def _assert_action_allowed_for_mission(*, mission: Mission, action_name: str) -> None:
    allowed_actions = _mission_allowed_actions(mission.metadata_json)
    if not allowed_actions:
        return
    registry = get_default_action_registry()
    try:
        definition = registry.get(action_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action {action_name!r} is not registered for mission-scoped launch.",
        ) from exc
    permitted_names = {definition.name, *definition.aliases}
    if not permitted_names.intersection(allowed_actions):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "MISSION_ACTION_NOT_ALLOWED",
                "message": f"Action {action_name!r} is outside this mission's allowed_actions scope.",
                "allowed_actions": allowed_actions,
            },
        )

def _provider_mode(provider: str, side_effect_class: SideEffectClass) -> Literal["local", "external", "mixed"]:
    if side_effect_class.value.startswith("external_"):
        return "external"
    if provider.startswith("local"):
        return "local"
    return "mixed"

def _requires_runtime_authority(side_effect_class: SideEffectClass) -> bool:
    return side_effect_class.has_side_effect or side_effect_class.value.startswith("external_")

def _adapter_side_effect_classification(side_effect_class: SideEffectClass) -> str:
    """Map runtime tool side-effect classes onto the persisted adapter contract."""
    if side_effect_class == SideEffectClass.NONE:
        return "none"
    if side_effect_class == SideEffectClass.INTERNAL_READ:
        return "read_only"
    if side_effect_class == SideEffectClass.INTERNAL_WRITE:
        return "non_idempotent_write"
    if side_effect_class in {
        SideEffectClass.EXTERNAL_READ,
        SideEffectClass.EXTERNAL_WRITE,
        SideEffectClass.EXTERNAL_SEND,
        SideEffectClass.EXTERNAL_PUBLISH,
    }:
        return side_effect_class.value
    return "external_side_effect"

def _action_definition(action_name: str) -> ActionDefinition:
    registry = get_default_action_registry()
    try:
        return registry.get(action_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

def _validate_exposed_action(action_name: str) -> None:
    if action_name not in EXPOSED_ACTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action {action_name!r} is not exposed by ability-runtime.",
        )

