"""Unit tests for Mission Composition Engine (ADR-0008)."""

from __future__ import annotations

from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.job_catalog import get_business_job, list_business_jobs
from backend.services.mission_composition.plan_compiler import (
    compile_planned_steps,
    compile_task_graph_preview,
)
from backend.services.mission_composition.proposal_store import clear_proposals_for_tests
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.operating_charter import default_operating_charter

ROOFING_INSTRUCTION = (
    "Research roofing companies in Austin, identify three strong prospects, "
    "draft personalized introductions, and bring them to me before anything is sent."
)


def setup_function() -> None:
    clear_proposals_for_tests()


def test_interpreter_roofing_forbids_send_and_targets_austin() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    assert "research prospects" in intent.requested_outcomes
    assert "qualify prospects" in intent.requested_outcomes
    assert "draft introductions" in intent.requested_outcomes
    assert "send emails" not in intent.requested_outcomes
    assert any("do not send" in c.lower() for c in intent.constraints)
    assert "gtm.email_send" in intent.forbidden_outcomes
    assert intent.target_entities
    assert intent.target_entities[0].location
    assert intent.target_entities[0].location.lower() == "austin"
    assert intent.target_entities[0].industry
    assert intent.target_entities[0].industry.lower() == "roofing"
    assert "research" not in intent.target_entities[0].industry.lower()
    assert "identify" not in intent.target_entities[0].location.lower()


def test_interpreter_stops_location_before_trailing_verbs() -> None:
    intent = interpret_instruction(
        "research roofing companies in fayetteville AR identify three strong competors"
    )
    assert intent.target_entities
    assert intent.target_entities[0].industry.lower() == "roofing"
    assert intent.target_entities[0].location.lower() == "fayetteville ar"
    assert "identify" not in intent.target_entities[0].location.lower()
    assert "research prospects" in intent.requested_outcomes


def test_interpreter_does_not_invent_actions() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    # Intent has outcomes and constraints only — no action names except forbidden send token.
    for outcome in intent.requested_outcomes:
        assert "." not in outcome


def test_job_catalog_has_sales_gtm_and_catalog_only_accounting() -> None:
    keys = {job.job_key for job in list_business_jobs()}
    assert "research.discover_prospects" in keys
    assert "email.prepare_outreach" in keys
    assert "email.deliver_outreach" in keys
    accounting = list_business_jobs(maturity="catalog_only")
    assert any(job.job_key.startswith("accounting.") for job in accounting)
    assert get_business_job("sales.qualify_prospects").candidate_actions


def test_route_jobs_excludes_send_when_forbidden() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    keys = [job.job_key for job in jobs]
    assert "research.discover_prospects" in keys
    assert "sales.qualify_prospects" in keys
    assert "email.prepare_outreach" in keys
    assert "email.deliver_outreach" not in keys


def test_capability_resolver_selects_draft_not_send() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    selections, _missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    ready_actions = {
        item.action_name for item in selections if item.selection_status == "selected" and item.readiness == "ready"
    }
    assert "gtm.email_draft" in ready_actions or "sales.draft_followup" in ready_actions
    assert "gtm.email_send" not in ready_actions
    assert "web.research" in ready_actions or "sales.research" in ready_actions
    assert "sales.qualify" in ready_actions


def test_plan_compiler_builds_non_linear_dependency_edges() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    selections, _ = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    steps = compile_planned_steps(selections, intent=intent)
    graph = compile_task_graph_preview(steps)
    assert graph["nodes"]
    # At least one edge should exist when qualify depends on research.
    if len(graph["nodes"]) > 1:
        assert isinstance(graph["edges"], list)
    # No checkbox-linear assumption: edges only from job depends_on.
    for edge in graph["edges"]:
        assert edge["dependency_type"] == "depends_on"


def test_composed_graph_populates_web_research_query() -> None:
    intent = interpret_instruction(ROOFING_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    selections, _ = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    steps = compile_planned_steps(selections, intent=intent)
    graph = compile_task_graph_preview(steps)
    research_nodes = [
        node
        for node in graph["nodes"]
        if node["input_contract"]["tool_invocation"]["action"] in {"web.research", "web.search"}
    ]
    assert research_nodes
    for node in research_nodes:
        tool_input = node["input_contract"]["tool_invocation"]["input"]
        assert isinstance(tool_input.get("query"), str) and tool_input["query"].strip()
        assert "roofing" in tool_input["query"].lower() or "austin" in tool_input["query"].lower()


def test_route_jobs_expands_dependencies_transitively() -> None:
    intent = interpret_instruction("Draft personalized introductions for three strong prospects. Do not send messages.")
    jobs = route_jobs_for_intent(intent)
    keys = {job.job_key for job in jobs}
    assert "email.prepare_outreach" in keys
    # Transitive: prepare → qualify/enrich → discover
    assert "sales.qualify_prospects" in keys
    assert "research.discover_prospects" in keys


def test_send_without_gmail_is_not_ready() -> None:
    service = MissionCompositionService(db=None)
    record = service.compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction="Research roofing companies in Austin and send personalized introductions to three prospects.",
    )
    # Default charter never_do may block send; either way start must not claim delivery is ready.
    assert "gtm.email_send" not in record.allowed_actions or record.ready_to_start is False
    if any(item.job_key == "email.deliver_outreach" for item in record.ability_selections):
        assert record.ready_to_start is False


def test_calendar_briefing_instruction_routes_to_calendar_job() -> None:
    intent = interpret_instruction(
        "Provide a calendar briefing: read calendar for upcoming commitments and prepare meeting briefs."
    )
    assert "calendar briefing" in intent.requested_outcomes
    jobs = route_jobs_for_intent(intent)
    assert any(job.job_key == "ops.calendar_briefing" for job in jobs)


def test_credential_reference_is_copied_into_graph_input_contract() -> None:
    from backend.services.mission_composition.contracts import AbilitySelection

    selection = AbilitySelection(
        job_key="email.deliver_outreach",
        ability_id="gtm-email-send",
        action_name="gtm.email_send",
        selection_status="selected",
        selection_reason="connected gmail",
        readiness="ready",
        vertical_role="vertical.email",
        side_effect_class="external_send",
        credential_reference={
            "schema_version": 1,
            "credential_id": "gmail-email",
            "provider": "external_email",
            "credential_type": "api_key",
        },
    )
    intent = interpret_instruction("Send a follow-up email to a prospect.")
    steps = compile_planned_steps([selection], intent=intent)
    graph = compile_task_graph_preview(steps, selections=[selection], approved_by="tester")
    node = graph["nodes"][0]
    cred = node["input_contract"].get("credential_reference")
    assert cred is not None
    assert cred["credential_id"] == "gmail-email"
    assert cred["provider"] == "external_email"
    assert cred["credential_type"] == "api_key"
    auth = node["input_contract"]["execution_constraints"]["side_effect_authorization"]
    assert auth["allowed_actions"] == ["gtm.email_send"]
    assert auth["approved_by"] == "tester"


def test_confirm_rejects_unready_proposal() -> None:
    from unittest.mock import MagicMock

    from backend.services.mission_composition.service import MissionCompositionError

    # Send without Gmail / charter perform → server recomposes unready and refuses confirm.
    instruction = "Research roofing companies in Austin and send personalized introductions to three prospects."
    service = MissionCompositionService(db=MagicMock())
    # Compose with no credential connectivity (MagicMock list returns empty via exception/empty).
    service._db = None  # type: ignore[assignment]
    record = service.compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction=instruction,
    )
    assert record.ready_to_start is False or "gtm.email_send" not in record.allowed_actions
    service = MissionCompositionService(db=MagicMock())
    try:
        service.confirm(
            tenant_id="11111111-1111-1111-1111-111111111111",
            proposal_id=record.proposal_id,
            composition=record.model_dump(mode="json"),
        )
        raise AssertionError("expected PROPOSAL_NOT_READY or NO_RUNTIME_ACTIONS")
    except MissionCompositionError as exc:
        assert exc.code in {"PROPOSAL_NOT_READY", "NO_RUNTIME_ACTIONS"}


def test_confirm_ignores_client_forged_allowed_actions() -> None:
    from unittest.mock import MagicMock, patch

    compose_service = MissionCompositionService(db=None)
    record = compose_service.compose(
        tenant_id="11111111-1111-1111-1111-111111111111",
        instruction=ROOFING_INSTRUCTION,
    )
    forged = record.model_dump(mode="json")
    forged["allowed_actions"] = [*list(record.allowed_actions), "gtm.email_send"]
    forged["ready_to_start"] = True
    forged["ability_selections"] = [
        *list(forged.get("ability_selections") or []),
        {
            "job_key": "email.deliver_outreach",
            "action_name": "gtm.email_send",
            "selection_status": "selected",
            "selection_reason": "forged",
            "readiness": "ready",
            "vertical_role": "vertical.email",
            "side_effect_class": "external_send",
            "alternatives": [],
            "requires_connection": False,
        },
    ]

    service = MissionCompositionService(db=MagicMock())
    # Recompose must strip send even if client forges the body.
    with (
        patch("backend.services.mission_composition.service.QuotaEnforcementService") as quota_cls,
        patch("backend.services.mission_composition.service.MissionRepository") as mission_repo_cls,
        patch("backend.services.mission_composition.service.MissionPlanRepository") as plan_repo_cls,
        patch("backend.services.mission_composition.service.BusinessProfileRepository") as profile_cls,
        patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as cred_cls,
    ):
        import uuid

        from backend.domain.enums import MissionPlanStatus
        from backend.domain.mission import Mission, MissionPlan

        profile_cls.return_value.get_active_profile_for_tenant.return_value = None
        cred_cls.return_value.list_for_tenant.return_value = []
        quota_cls.return_value.enforce_mission_budget_gate.return_value = None
        quota_cls.return_value.check_and_record_mission_creation.return_value = None
        mid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        pid = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

        def _add(m: Mission) -> Mission:
            m.id = mid
            return m

        mission_repo_cls.return_value.add.side_effect = _add
        plan_repo_cls.return_value.create_or_get_active_for_mission.return_value = MissionPlan(
            id=pid,
            tenant_id="11111111-1111-1111-1111-111111111111",
            mission_id=mid,
            status=MissionPlanStatus.DRAFT.value,
            metadata_json={},
        )

        result = service.confirm(
            tenant_id="11111111-1111-1111-1111-111111111111",
            proposal_id=record.proposal_id,
            composition=forged,
        )
    assert "gtm.email_send" not in result["allowed_actions"]
    assert result["mission_id"] == str(mid)


def test_matched_credential_id_not_hardcoded_hint() -> None:
    from backend.services.mission_composition.capability_resolver import evaluate_action_candidate
    from backend.services.mission_composition.job_catalog import get_business_job
    from backend.services.operating_charter import dogfood_operating_charter

    job = get_business_job("email.deliver_outreach")
    selection = evaluate_action_candidate(
        job=job,
        action_name="gtm.email_send",
        charter=dogfood_operating_charter(),
        connected_credential_ids={"ajenda-email"},
        connected_integrations={"gmail"},
        forbid_actions=set(),
        preferred_credential_by_integration={"gmail": ("ajenda-email", "platform_master")},
        credential_type_by_id={"ajenda-email": "platform_master"},
    )
    assert selection.readiness == "ready"
    assert selection.credential_reference is not None
    assert selection.credential_reference["credential_id"] == "ajenda-email"
    assert selection.credential_reference["credential_type"] == "platform_master"


def test_confirm_proposal_id_miss_returns_not_found() -> None:
    from unittest.mock import MagicMock

    from backend.services.mission_composition.proposal_store import clear_proposals_for_tests
    from backend.services.mission_composition.service import MissionCompositionError

    clear_proposals_for_tests()
    service = MissionCompositionService(db=MagicMock())
    try:
        service.confirm(
            tenant_id="11111111-1111-1111-1111-111111111111",
            proposal_id="missing-proposal-id",
            composition=None,
        )
        raise AssertionError("expected PROPOSAL_NOT_FOUND")
    except MissionCompositionError as exc:
        assert exc.code == "PROPOSAL_NOT_FOUND"


def test_connected_sets_maps_provider_without_integration_attr() -> None:
    from types import SimpleNamespace

    from backend.services.mission_composition.service import _integrations_for_credential

    gmail = SimpleNamespace(
        provider="external_email",
        credential_id="ajenda-email",
        trusted_destination_hosts=["gmail.googleapis.com"],
    )
    assert "gmail" in _integrations_for_credential(gmail)
    hubspot = SimpleNamespace(
        provider="external_crm",
        credential_id="tenant-crm-key",
        trusted_destination_hosts=["api.hubapi.com"],
    )
    assert "hubspot" in _integrations_for_credential(hubspot)


def test_compose_service_roofing_ready_without_db() -> None:
    service = MissionCompositionService(db=None)
    record = service.compose(tenant_id="11111111-1111-1111-1111-111111111111", instruction=ROOFING_INSTRUCTION)
    assert record.proposal_id
    assert record.allowed_actions
    assert "gtm.email_send" not in record.allowed_actions
    assert any("do not send" in c.lower() for c in record.intent.constraints)
    assert record.allowed_actions_provenance.selected_by == "mission_composition_engine"
    assert record.allowed_actions_provenance.user_supplied is False
    assert record.composition_provenance.grants_execution_authority is False
    assert record.task_graph_preview.get("nodes")
    # Draft-only sales path should be ready without HubSpot when internal paths exist.
    assert record.ready_to_start is True
    # Every node carries a non-empty tool input for invoke validation.
    for node in record.task_graph_preview["nodes"]:
        inv = node["input_contract"]["tool_invocation"]
        assert inv["action"]
        assert isinstance(inv["input"], dict)
        if inv["action"] == "web.research":
            assert inv["input"].get("query")
        if inv["action"] == "gtm.email_draft":
            assert inv["input"].get("recipient") == "pending.binding@invalid.local"
            assert inv["input"].get("context", {}).get("binding_required") is True
