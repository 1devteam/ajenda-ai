from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.provider_runtime_credential_repository import ProviderRuntimeCredentialRepository
from backend.services.brain_mission_catalog import BRAIN_MISSIONS, BrainMissionSpec
from backend.services.operating_charter import (
    OperatingCharter,
    OperatingCharterViolation,
    assert_action_allowed,
    load_operating_charter,
)
from backend.services.tools.action_registry import get_default_action_registry
from backend.services.tools.schemas import SideEffectClass

BrainMissionStatus = Literal["READY", "BLOCKED", "NEEDS_PROFILE", "NEEDS_CREDENTIAL", "PARTIAL"]


@dataclass(frozen=True, slots=True)
class BrainMissionReadiness:
    mission_id: str
    mission: str
    outcome: str
    action: str
    tier: str
    status: BrainMissionStatus
    note: str

    def to_api(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission": self.mission,
            "outcome": self.outcome,
            "action": self.action,
            "tier": self.tier,
            "status": self.status,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class BrainCapabilityReport:
    schema_version: int
    charter_source: str
    profile_ready: bool
    missions: tuple[BrainMissionReadiness, ...]

    def to_api(self) -> dict[str, Any]:
        statuses = [item.status for item in self.missions]
        return {
            "schema_version": self.schema_version,
            "charter_source": self.charter_source,
            "profile_ready": self.profile_ready,
            "summary": {
                "ready": statuses.count("READY"),
                "partial": statuses.count("PARTIAL"),
                "blocked": statuses.count("BLOCKED"),
                "needs_profile": statuses.count("NEEDS_PROFILE"),
                "needs_credential": statuses.count("NEEDS_CREDENTIAL"),
                "total": len(self.missions),
            },
            "missions": [item.to_api() for item in self.missions],
        }


def _profile_text(facts: dict[str, Any], category: str) -> str:
    value = facts.get(category)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        nested = value.get("value")
        if isinstance(nested, str):
            return nested.strip()
    return ""


def _profile_has_memory_context(facts: dict[str, Any]) -> bool:
    if _profile_text(facts, "business_name"):
        return True
    products = facts.get("products_services")
    if isinstance(products, dict):
        items = products.get("items")
        if isinstance(items, list) and items:
            return True
        value = products.get("value")
        if isinstance(value, str) and value.strip():
            return True
    if isinstance(products, list) and products:
        return True
    return False


def _side_effect_for_action(action_name: str) -> SideEffectClass:
    registry = get_default_action_registry()
    return registry.get(action_name).side_effect_class


def _credential_available(*, session: Session, tenant_id: str, action_name: str) -> bool:
    records = ProviderRuntimeCredentialRepository(session).list_for_tenant(tenant_id=tenant_id)
    for record in records:
        if record.revoked or not record.enabled:
            continue
        allowed_actions = record.allowed_actions if isinstance(record.allowed_actions, list) else []
        if action_name in allowed_actions:
            return True
    return False


def _assess_mission(
    *,
    spec: BrainMissionSpec,
    charter: OperatingCharter,
    profile_ready: bool,
    credential_available: bool,
) -> BrainMissionReadiness:
    action = spec["action"]
    side_effect = _side_effect_for_action(action)

    try:
        assert_action_allowed(action_name=action, side_effect_class=side_effect, charter=charter)
    except OperatingCharterViolation as exc:
        return BrainMissionReadiness(
            mission_id=spec["mission_id"],
            mission=spec["mission"],
            outcome=spec["outcome"],
            action=action,
            tier=spec["tier"],
            status="BLOCKED",
            note=exc.message,
        )

    if spec["mission_id"] in {"M1", "M2", "M3"} and not profile_ready:
        return BrainMissionReadiness(
            mission_id=spec["mission_id"],
            mission=spec["mission"],
            outcome=spec["outcome"],
            action=action,
            tier=spec["tier"],
            status="NEEDS_PROFILE",
            note="Add business name or products & services on Business info.",
        )

    if spec["mission_id"] == "M11":
        if not credential_available:
            return BrainMissionReadiness(
                mission_id=spec["mission_id"],
                mission=spec["mission"],
                outcome=spec["outcome"],
                action=action,
                tier=spec["tier"],
                status="NEEDS_CREDENTIAL",
                note=(
                    "Connect Gmail OAuth, tenant SMTP (any host), or the ajenda-email "
                    "platform lane for external send."
                ),
            )
        if not get_settings().llm_ready:
            return BrainMissionReadiness(
                mission_id=spec["mission_id"],
                mission=spec["mission"],
                outcome=spec["outcome"],
                action=action,
                tier=spec["tier"],
                status="PARTIAL",
                note="Charter and email ready; set AJENDA_LLM_API_KEY for LLM drafts in the capstone path.",
            )
        return BrainMissionReadiness(
            mission_id=spec["mission_id"],
            mission=spec["mission"],
            outcome=spec["outcome"],
            action=action,
            tier=spec["tier"],
            status="READY",
            note="Capstone path ready: M10 research → M7 draft → review queue → send → M9 CRM.",
        )

    if spec.get("optional_credential") and not credential_available:
        return BrainMissionReadiness(
            mission_id=spec["mission_id"],
            mission=spec["mission"],
            outcome=spec["outcome"],
            action=action,
            tier=spec["tier"],
            status="READY",
            note="Brain path ready; connect CRM plugin for enriched external context.",
        )

    if action in {"gtm.email_draft", "sales.draft_followup"}:
        if get_settings().llm_ready:
            return BrainMissionReadiness(
                mission_id=spec["mission_id"],
                mission=spec["mission"],
                outcome=spec["outcome"],
                action=action,
                tier=spec["tier"],
                status="READY",
                note="LLM drafting enabled; artifacts persist to review queue.",
            )
        return BrainMissionReadiness(
            mission_id=spec["mission_id"],
            mission=spec["mission"],
            outcome=spec["outcome"],
            action=action,
            tier=spec["tier"],
            status="PARTIAL",
            note="Template draft path works; set AJENDA_LLM_API_KEY for LLM generation.",
        )

    return BrainMissionReadiness(
        mission_id=spec["mission_id"],
        mission=spec["mission"],
        outcome=spec["outcome"],
        action=action,
        tier=spec["tier"],
        status="READY",
        note="Charter allows launch through ability-runtime.",
    )


def build_brain_capability_report(*, session: Session, tenant_id: str) -> BrainCapabilityReport:
    profile = BusinessProfileRepository(session).get_active_profile_for_tenant(tenant_id=tenant_id)
    facts = profile.approved_facts if profile is not None and isinstance(profile.approved_facts, dict) else {}
    charter = load_operating_charter(approved_facts=facts)
    profile_ready = _profile_has_memory_context(facts)

    missions: list[BrainMissionReadiness] = []
    for spec in BRAIN_MISSIONS:
        credential_available = _credential_available(session=session, tenant_id=tenant_id, action_name=spec["action"])
        missions.append(
            _assess_mission(
                spec=spec,
                charter=charter,
                profile_ready=profile_ready,
                credential_available=credential_available,
            )
        )

    return BrainCapabilityReport(
        schema_version=1,
        charter_source=charter.source,
        profile_ready=profile_ready,
        missions=tuple(missions),
    )
