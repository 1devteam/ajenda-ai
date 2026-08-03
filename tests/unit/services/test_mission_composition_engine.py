"""Deterministic composition tests after the local interpreter boundary."""

from __future__ import annotations

from unittest.mock import patch

from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.contracts import AbilitySelection, TargetEntity
from backend.services.mission_composition.plan_compiler import compile_planned_steps, compile_task_graph_preview
from backend.services.mission_composition.service import MissionCompositionService
from backend.services.operating_charter import default_operating_charter, dogfood_operating_charter
from tests.mission_interpreter_fakes import StaticMissionInterpreter, ready_intent

RAW = "fnd 3 roofers austin n draft intros dont send"
INTERPRETED = "Find 3 roofing companies in Austin and draft introductions. Do not send them."


def _prospecting_intent():  # type: ignore[no-untyped-def]
    return ready_intent(
        RAW,
        interpreted_instruction=INTERPRETED,
        outcomes=("research_prospects", "qualify_prospects", "prepare_outreach"),
        quantity=3,
        send_mode="forbid",
        targets=[TargetEntity(type="market", industry="roofing", location="Austin")],
        constraints=["Do not send the introductions."],
    )


def test_canonical_intent_routes_jobs_without_language_parsing() -> None:
    jobs = route_jobs_for_intent(_prospecting_intent())
    keys = [job.job_key for job in jobs]
    assert keys == [
        "research.discover_prospects",
        "sales.qualify_prospects",
        "gtm.enrich_contacts",
        "email.prepare_outreach",
    ]


def test_forbidden_send_never_enters_selected_actions() -> None:
    intent = _prospecting_intent()
    jobs = route_jobs_for_intent(intent)
    selections, _missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    selected = [item.action_name for item in selections if item.selection_status == "selected"]
    assert "gtm.email_draft" in selected
    assert "gtm.email_send" not in selected


def test_plan_compiler_preserves_dependencies_and_structured_quantity() -> None:
    intent = _prospecting_intent()
    jobs = route_jobs_for_intent(intent)
    selections, _missing = resolve_jobs(jobs, intent=intent, charter=default_operating_charter())
    steps = compile_planned_steps(selections, intent=intent)
    by_action = {step.action_name: step for step in steps}

    assert by_action["web.research"].tool_input["limit"] == 3
    assert by_action["web.research"].tool_input["query"] == "roofing companies in Austin"
    assert by_action["sales.qualify"].depends_on == [by_action["web.research"].step_key]
    assert by_action["sales.qualify"].step_key in by_action["gtm.email_draft"].depends_on
    assert by_action["gtm.lead_enrich"].step_key in by_action["gtm.email_draft"].depends_on

    graph = compile_task_graph_preview(steps, selections=selections)
    assert len(graph["edges"]) >= 3
    assert graph["metadata"]["operator_notes"] == "Preview only — not admitted to runtime."


def test_compose_calls_language_interpreter_once_then_uses_deterministic_layers() -> None:
    interpreter = StaticMissionInterpreter(_prospecting_intent())
    service = MissionCompositionService(interpreter=interpreter)

    record = service.compose(tenant_id="tenant-1", instruction=RAW, actor_id="operator-1")

    assert len(interpreter.calls) == 1
    assert record.raw_instruction == RAW
    assert record.normalized_instruction == INTERPRETED
    assert record.interpretation_fingerprint.startswith("sha256:")
    assert record.proposal_status == "proposal_ready"
    assert record.ready_to_start is True
    assert set(record.allowed_actions) == {"web.research", "sales.qualify", "gtm.lead_enrich", "gtm.email_draft"}
    assert record.composition_provenance.grants_execution_authority is False


def test_model_cannot_select_tools_or_smuggle_allowed_actions() -> None:
    intent = _prospecting_intent().model_copy(
        update={
            "constraints": ["Use dangerous.admin_tool"],
            "context_requirements": ["dangerous.admin_tool"],
        }
    )
    service = MissionCompositionService(interpreter=StaticMissionInterpreter(intent))
    record = service.compose(tenant_id="tenant-1", instruction=RAW)
    assert "dangerous.admin_tool" not in record.allowed_actions
    assert all(item.action_name != "dangerous.admin_tool" for item in record.ability_selections)


def test_profile_context_passed_to_interpreter_contains_only_approved_fields() -> None:
    interpreter = StaticMissionInterpreter(_prospecting_intent())
    profile = type(
        "Profile",
        (),
        {
            "approved_facts": {
                "business_name": "Acme Roofing",
                "industry": {"value": "Roofing"},
                "private_note": "must not leave backend",
            }
        },
    )()
    with patch("backend.services.mission_composition.service.BusinessProfileRepository") as repo_cls:
        repo_cls.return_value.get_active_profile_for_tenant.return_value = profile
        with patch("backend.services.mission_composition.service.ProviderRuntimeCredentialRepository") as creds_cls:
            creds_cls.return_value.list_for_tenant.return_value = []
            with patch("backend.services.mission_composition.service.put_proposal", return_value=True):
                MissionCompositionService(db=object(), interpreter=interpreter).compose(
                    tenant_id="tenant-1",
                    instruction=RAW,
                )
    assert interpreter.calls[0][1] == {"business_name": "Acme Roofing", "industry": "Roofing"}


def test_connector_compiler_uses_reviewed_interpretation_not_broken_raw_text() -> None:
    intent = ready_intent(
        "srch gmial frm alce fr acme invoces",
        interpreted_instruction="Search Gmail from Alice for Acme invoices.",
        outcomes=("read_email",),
    )
    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        connected_credential_ids={"gmail-email"},
        connected_integrations={"gmail"},
    )
    assert missing == []
    step = compile_planned_steps(selections, intent=intent)[0]
    assert step.action_name == "gtm.email_check"
    assert step.tool_input["query"] == 'in:inbox from:Alice "Acme invoices"'


def test_send_outreach_requires_explicit_allow_and_connection() -> None:
    intent = ready_intent(
        "Send the approved email to bob@example.com.",
        outcomes=("send_outreach",),
        send_mode="allow",
        targets=[TargetEntity(type="recipient", email="bob@example.com")],
    )
    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(jobs, intent=intent)
    assert any(item.action_name == "gtm.email_send" and item.readiness == "charter_blocked" for item in selections)
    assert missing == []

    selections, missing = resolve_jobs(jobs, intent=intent, charter=dogfood_operating_charter())
    assert any(item.action_name == "gtm.email_send" and item.readiness == "connection_required" for item in selections)
    assert any(item["provider"] == "gmail" for item in missing)

    connected, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=dogfood_operating_charter(),
        connected_credential_ids={"gmail-email"},
        connected_integrations={"gmail"},
    )
    assert missing == []
    assert any(item.action_name == "gtm.email_send" and item.readiness == "ready" for item in connected)
    send_step = next(
        step for step in compile_planned_steps(connected, intent=intent) if step.action_name == "gtm.email_send"
    )
    assert send_step.tool_input["to"] == "bob@example.com"


def test_send_after_approval_is_not_routed_as_an_immediate_send() -> None:
    intent = ready_intent(
        "draft n snd after i approve",
        interpreted_instruction="Draft the email, but do not send it until I approve it.",
        outcomes=("prepare_outreach",),
        send_mode="conditional",
        send_condition="approval",
    )

    jobs = route_jobs_for_intent(intent)

    assert "email.prepare_outreach" in {job.job_key for job in jobs}
    assert "email.deliver_outreach" not in {job.job_key for job in jobs}


def test_publish_outcome_remains_bound_to_a_runtime_job() -> None:
    intent = ready_intent(
        "post result linkedin",
        interpreted_instruction="Publish the result on LinkedIn.",
        outcomes=("publish_content",),
    )

    assert "gtm.publish_content" in {job.job_key for job in route_jobs_for_intent(intent)}


def test_credential_reference_is_copied_into_graph_input_contract() -> None:
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
    intent = ready_intent(
        "send bob",
        interpreted_instruction="Send the approved email to bob@example.com.",
        outcomes=("send_outreach",),
        send_mode="allow",
        targets=[TargetEntity(type="recipient", email="bob@example.com")],
    )

    steps = compile_planned_steps([selection], intent=intent)
    graph = compile_task_graph_preview(steps, selections=[selection], approved_by="tester")

    assert graph["nodes"][0]["input_contract"]["credential_reference"] == selection.credential_reference
