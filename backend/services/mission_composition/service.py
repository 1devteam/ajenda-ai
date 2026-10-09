"""Mission composition public service boundary.

The service preserves the established import/patch surface while delegating
proposal, confirmation, and existing-mission compilation to responsibility-owned
phase modules. Compose remains read-only; confirm/compile never queue work.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.repositories.execution_task_repository import ExecutionTaskRepository
from backend.repositories.mission_plan_repository import MissionPlanRepository
from backend.repositories.mission_repository import MissionRepository
from backend.repositories.provider_runtime_credential_repository import ProviderRuntimeCredentialRepository
from backend.services.business_profile.record_sync import build_profile_brief
from backend.services.mission_composition.compile_phase import MissionCompositionCompilePhase
from backend.services.mission_composition.confirmation_phase import MissionCompositionConfirmationPhase
from backend.services.mission_composition.contracts import MissionIntent, is_ranking_only_instruction
from backend.services.mission_composition.deliverable_contract import (
    DeliverableFieldRequirement,
    DeliverableRequest,
)
from backend.services.mission_composition.plan_compiler import compile_planned_steps
from backend.services.mission_composition.proposal_phase import MissionCompositionProposalPhase
from backend.services.mission_composition.semantic_vocabulary import TenantSemanticOverride
from backend.services.mission_composition.service_contracts import COMPILER_NAME as COMPILER_NAME
from backend.services.mission_composition.service_contracts import COMPILER_VERSION as COMPILER_VERSION
from backend.services.mission_composition.service_contracts import (
    MissionCompositionError as MissionCompositionError,
)
from backend.services.mission_composition.structured_planner import StructuredPlannerProvider
from backend.services.operating_charter import default_operating_charter, load_operating_charter
from backend.services.quota_enforcement import QuotaEnforcementService


def _runtime_deliverable_request(intent: MissionIntent) -> DeliverableRequest | None:
    """Return the explicit request or the server-declared research artifact contract.

    Short operator requests often name the research outcome without spelling out
    a report field list.  The compiler already owns that outcome and its
    ``prospect_candidates`` artifact, so it can persist the minimal typed read
    model needed to display that artifact.  No rows are invented here; runtime
    completion still validates the materialized payload against this contract.
    """

    if intent.deliverable_request is not None:
        return intent.deliverable_request
    outcomes = set(intent.requested_outcomes)
    if not outcomes.intersection(
        {
            "research_prospects",
            "read_crm",
            "qualify_prospects",
            "prepare_outreach",
            "observe_web_page",
            "verify_public_identity",
        }
    ):
        return None

    fields: list[DeliverableFieldRequirement] = []
    if "research_prospects" in outcomes:
        fields.extend(
            (
                DeliverableFieldRequirement(field_key="website", source_text="website"),
                DeliverableFieldRequirement(field_key="research_summary", source_text="research summary"),
                DeliverableFieldRequirement(field_key="sources", source_text="sources"),
            )
        )
    if "read_crm" in outcomes or "qualify_prospects" in outcomes:
        fields.append(DeliverableFieldRequirement(field_key="company_name", source_text="company name"))
    if "qualify_prospects" in outcomes:
        fields.extend(
            (
                DeliverableFieldRequirement(field_key="qualification_score", source_text="qualification score"),
                DeliverableFieldRequirement(field_key="qualification_reasons", source_text="qualification reasons"),
                DeliverableFieldRequirement(field_key="qualification_evidence", source_text="qualification evidence"),
            )
        )
    if "prepare_outreach" in outcomes:
        fields.append(DeliverableFieldRequirement(field_key="drafts", source_text="introduction drafts"))
    if "observe_web_page" in outcomes:
        fields.extend(
            (
                DeliverableFieldRequirement(field_key="source_url", source_text="source URL"),
                DeliverableFieldRequirement(field_key="final_url", source_text="final URL"),
                DeliverableFieldRequirement(field_key="title", source_text="page title"),
                DeliverableFieldRequirement(field_key="extracted_observations", source_text="observed page content"),
                DeliverableFieldRequirement(field_key="observation_timestamp", source_text="observation timestamp"),
                DeliverableFieldRequirement(field_key="browser_trace", source_text="browser step trace"),
                DeliverableFieldRequirement(field_key="blocked_requests", source_text="blocked requests"),
                DeliverableFieldRequirement(field_key="observation_satisfied", source_text="observation completion"),
            )
        )
    if "verify_public_identity" in outcomes:
        fields.extend(
            (
                DeliverableFieldRequirement(field_key="source_url", source_text="source URL"),
                DeliverableFieldRequirement(field_key="expected_company", source_text="expected company"),
                DeliverableFieldRequirement(field_key="expected_industry", source_text="expected industry"),
                DeliverableFieldRequirement(field_key="expected_location", source_text="expected location"),
                DeliverableFieldRequirement(field_key="identity_status", source_text="identity status"),
                DeliverableFieldRequirement(field_key="identity_evidence_urls", source_text="identity evidence URLs"),
                DeliverableFieldRequirement(field_key="identity_match_reasons", source_text="identity match reasons"),
                DeliverableFieldRequirement(field_key="identity_gaps", source_text="identity gaps"),
            )
        )

    return DeliverableRequest(
        scope="mission" if {"observe_web_page", "verify_public_identity"}.intersection(outcomes) else "per_prospect",
        fields=tuple(dict((field.field_key, field) for field in fields).values()),
    )


def _profile_context(profile: Any) -> dict[str, Any]:
    if profile is None:
        return {}
    facts = getattr(profile, "approved_facts", None) or {}
    if not isinstance(facts, dict):
        return {}
    context: dict[str, Any] = {}
    for key in (
        "business_name",
        "company",
        "industry",
        "products_services",
        "target_customers",
        "differentiators",
        "description",
        "service_area",
        "operator_notes",
    ):
        value = facts.get(key)
        if isinstance(value, (str, list, tuple)) and value:
            context[key] = value.strip() if isinstance(value, str) else list(value)
        elif isinstance(value, dict) and value:
            context[key] = value
    # Feed the interpreter the same canonical vocabulary that runtime retrieval
    # emits; this prevents planner context from losing profile fields.
    normalized = build_profile_brief(
        approved_facts=facts,
        provenance=getattr(profile, "provenance", None),
    )["facts"]
    context.update(normalized)
    context["profile_id"] = str(getattr(profile, "id", ""))
    return context


def _tenant_semantic_overrides(profile: Any) -> tuple[tuple[TenantSemanticOverride, ...], tuple[str, ...]]:
    """Read approved tenant aliases without changing the shared vocabulary."""

    if profile is None:
        return (), ()
    facts = getattr(profile, "approved_facts", None) or {}
    if not isinstance(facts, dict) or "semantic_terminology_overrides" not in facts:
        return (), ()
    raw = facts.get("semantic_terminology_overrides")
    if not isinstance(raw, list):
        return (), ("tenant semantic terminology overrides must be a list",)

    profile_id = str(getattr(profile, "id", "unknown"))
    overrides: list[TenantSemanticOverride] = []
    conflicts: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            conflicts.append(f"tenant semantic override {index} must be an object")
            continue
        payload = dict(item)
        payload.setdefault("source_reference", f"business_profile:{profile_id}")
        payload.setdefault("version", "1.0.0")
        try:
            overrides.append(TenantSemanticOverride.model_validate(payload))
        except ValueError as exc:
            conflicts.append(f"tenant semantic override {index} is invalid: {str(exc)[:240]}")
    return tuple(overrides), tuple(conflicts)


def _acceptance_score_threshold(intent: MissionIntent) -> int:
    """Keep mission acceptance aligned with the qualification action contract."""

    if is_ranking_only_instruction(intent.objective):
        return 0
    if (
        intent.qualification_quantity is not None
        or "observe_contacts" in intent.requested_outcomes
        or "internal_crm_source" in set(intent.context_requirements)
        or "hubspot_source" in set(intent.context_requirements)
    ):
        return 5
    return 7


def _integrations_for_credential(record: object) -> set[str]:
    """Map persisted credential rows to integration tokens used by the resolver."""

    found: set[str] = set()
    provider = str(getattr(record, "provider", "") or "").strip().lower()
    credential_id = str(getattr(record, "credential_id", "") or "").strip().lower()
    hosts_raw = getattr(record, "trusted_destination_hosts", None) or []
    hosts = {str(host).strip().lower() for host in hosts_raw if str(host).strip()}

    # SMTP is send-only — never treat it as Gmail (gtm.email_check requires Gmail API).
    is_smtp = "smtp" in credential_id or (
        provider == "external_email" and str(getattr(record, "integration", "") or "").lower() == "smtp"
    )
    if is_smtp:
        found.add("smtp")
    elif provider == "external_email" or "gmail" in credential_id or "gmail.googleapis.com" in hosts:
        found.add("gmail")
    if provider == "external_crm" or "hubspot" in credential_id or "hubapi.com" in " ".join(hosts):
        found.add("hubspot")
    # Credential-id first so Contacts never masquerades as Calendar via shared API host.
    if "google-contacts" in credential_id or "contacts" in credential_id or "people.googleapis.com" in hosts:
        found.add("google_contacts")
    if (
        "google-calendar" in credential_id
        or ("calendar" in credential_id and "contacts" not in credential_id)
        or (
            "www.googleapis.com" in hosts
            and "people.googleapis.com" not in hosts
            and "google-contacts" not in credential_id
        )
    ):
        found.add("google_calendar")
    if "salesforce" in credential_id or any("salesforce.com" in host for host in hosts):
        found.add("salesforce")
    if "linkedin" in credential_id or "api.linkedin.com" in hosts:
        found.add("linkedin")
    if "github" in credential_id or "api.github.com" in hosts:
        found.add("github")

    # Explicit integration attr if present on future schemas / projections.
    integration = getattr(record, "integration", None)
    if isinstance(integration, str) and integration.strip():
        found.add(integration.strip().lower())
    return found


def _connected_sets(
    db: Session | None, tenant_id: str
) -> tuple[set[str], set[str], dict[str, tuple[str, str]], dict[str, str]]:
    """Return credential ids, integrations, preferred (id, type) per integration, type by id."""

    if db is None:
        return set(), set(), {}, {}
    try:
        records = ProviderRuntimeCredentialRepository(db).list_for_tenant(tenant_id=tenant_id)
    except Exception:
        return set(), set(), {}, {}
    credential_ids: set[str] = set()
    integrations: set[str] = set()
    preferred_by_integration: dict[str, tuple[str, str]] = {}
    type_by_credential_id: dict[str, str] = {}
    for record in records:
        if getattr(record, "revoked", False) or getattr(record, "deleted", False):
            continue
        if getattr(record, "enabled", True) is False:
            continue
        cred_id = str(record.credential_id)
        cred_type = str(getattr(record, "credential_type", "") or "api_key").strip() or "api_key"
        credential_ids.add(cred_id)
        type_by_credential_id[cred_id] = cred_type
        for integ in _integrations_for_credential(record):
            integrations.add(integ)
            preferred_by_integration.setdefault(integ, (cred_id, cred_type))
    for catalog_id, integ in (
        ("gmail-email", "gmail"),
        ("hubspot-crm", "hubspot"),
        ("google-calendar-read", "google_calendar"),
        ("google-contacts-read", "google_contacts"),
        ("salesforce-read", "salesforce"),
        ("linkedin-read", "linkedin"),
        ("github-read", "github"),
    ):
        if catalog_id in type_by_credential_id and integ in preferred_by_integration:
            preferred_by_integration[integ] = (catalog_id, type_by_credential_id[catalog_id])
    return credential_ids, integrations, preferred_by_integration, type_by_credential_id


def _load_charter(db: Session | None, tenant_id: str) -> Any:
    if db is None:
        return default_operating_charter()
    profile = BusinessProfileRepository(db).get_active_profile_for_tenant(tenant_id=tenant_id)
    facts = getattr(profile, "approved_facts", None) if profile is not None else None
    if not isinstance(facts, dict):
        facts = {}
    return load_operating_charter(approved_facts=facts)


class MissionCompositionService(
    MissionCompositionProposalPhase,
    MissionCompositionConfirmationPhase,
    MissionCompositionCompilePhase,
):
    """Coordinates composition phases while preserving the historical patch surface."""

    def __init__(
        self,
        db: Session | None = None,
        *,
        planner_provider: StructuredPlannerProvider | None = None,
    ) -> None:
        self._db = db
        self._planner_provider = planner_provider

    # Compatibility-sensitive dynamic bindings. Tests and integrations patch
    # these names through this module; phase implementations resolve them at
    # call time through these wrappers.
    def _business_profile_repository(self, db: Session) -> Any:
        return BusinessProfileRepository(db)

    def _mission_repository(self, db: Session) -> Any:
        return MissionRepository(db)

    def _mission_plan_repository(self, db: Session) -> Any:
        return MissionPlanRepository(db)

    def _execution_task_repository(self, db: Session) -> Any:
        return ExecutionTaskRepository(db)

    def _quota_enforcement_service(self, db: Session) -> Any:
        return QuotaEnforcementService(db)

    def _compile_planned_steps(self, *args: Any, **kwargs: Any) -> Any:
        return compile_planned_steps(*args, **kwargs)

    def _runtime_deliverable_request(self, intent: MissionIntent) -> DeliverableRequest | None:
        return _runtime_deliverable_request(intent)

    def _profile_context(self, profile: Any) -> dict[str, Any]:
        return _profile_context(profile)

    def _tenant_semantic_overrides(self, profile: Any) -> tuple[
        tuple[TenantSemanticOverride, ...], tuple[str, ...]
    ]:
        return _tenant_semantic_overrides(profile)

    def _acceptance_score_threshold(self, intent: MissionIntent) -> int:
        return _acceptance_score_threshold(intent)

    def _connected_sets(
        self, db: Session | None, tenant_id: str
    ) -> tuple[set[str], set[str], dict[str, tuple[str, str]], dict[str, str]]:
        return _connected_sets(db, tenant_id)

    def _load_charter(self, db: Session | None, tenant_id: str) -> Any:
        return _load_charter(db, tenant_id)

    def _binding_manifest_from_steps(self, steps: list[Any]) -> list[dict[str, Any]]:
        return _binding_manifest_from_steps(steps)

    def _required_credentials_from_selections(self, selections: list[Any]) -> list[dict[str, Any]]:
        return _required_credentials_from_selections(selections)

    def _side_effect_summary_from_selections(self, selections: list[Any]) -> list[dict[str, Any]]:
        return _side_effect_summary_from_selections(selections)


def _binding_manifest_from_steps(steps: list[Any]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for step in steps:
        bindings = getattr(step, "input_bindings", None) or []
        for binding in bindings:
            if not isinstance(binding, dict):
                continue
            manifest.append(
                {
                    "to_node": str(binding.get("to_step") or step.step_key),
                    "from_node": str(binding.get("from_step") or ""),
                    "output_path": str(binding.get("output_path") or ""),
                    "input_path": str(binding.get("input_path") or ""),
                    "required": True,
                    "action": step.action_name,
                }
            )
    return manifest


def _required_credentials_from_selections(selections: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in selections:
        if getattr(item, "selection_status", None) != "selected":
            continue
        if not getattr(item, "requires_connection", False) and getattr(item, "readiness", None) == "ready":
            continue
        status = "present" if getattr(item, "readiness", None) == "ready" else "missing"
        provider = None
        cred = getattr(item, "credential_reference", None)
        if isinstance(cred, dict):
            provider = cred.get("provider")
        out.append(
            {
                "action": item.action_name,
                "readiness": getattr(item, "readiness", None),
                "provider": provider,
                "status": status if getattr(item, "requires_connection", False) else "not_required",
            }
        )
    return out


def _side_effect_summary_from_selections(selections: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "action": item.action_name,
            "side_effect_class": item.side_effect_class,
            "readiness": item.readiness,
            "selection_status": item.selection_status,
        }
        for item in selections
        if item.selection_status == "selected"
    ]
