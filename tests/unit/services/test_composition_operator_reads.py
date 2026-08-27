"""Wave A: operator connector reads (LinkedIn, GitHub, Google Contacts).

Matrix contract: outcome → job → action → connection hint → language → inputs.
"""

from __future__ import annotations

from backend.services.mission_composition.action_inputs import build_action_input
from backend.services.mission_composition.capability_resolver import resolve_jobs, route_jobs_for_intent
from backend.services.mission_composition.contracts import (
    CAPABILITY_RESOLVER_VERSION,
    INTERPRETER_VERSION,
    JOB_CATALOG_VERSION,
)
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.job_catalog import get_business_job
from backend.services.operating_charter import default_operating_charter


def test_versions_bumped_for_wave_a() -> None:
    assert JOB_CATALOG_VERSION == "9"
    assert INTERPRETER_VERSION == "11"
    assert CAPABILITY_RESOLVER_VERSION == "8"


def test_linkedin_profile_read_composes_to_connection_required() -> None:
    intent = interpret_instruction("Read my LinkedIn profile")
    assert intent.requested_outcomes == ["read_linkedin"]
    assert intent.ambiguity == []
    jobs = route_jobs_for_intent(intent)
    assert {j.job_key for j in jobs} == {"ops.linkedin_profile_read"}
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations=set(),
    )
    assert len(selections) == 1
    sel = selections[0]
    assert sel.action_name == "linkedin.profile_read"
    assert sel.readiness == "connection_required"
    assert sel.connection_provider == "linkedin"
    assert missing and missing[0]["provider"] == "linkedin"
    payload = build_action_input(action_name="linkedin.profile_read", intent=intent)
    assert "fields" in payload


def test_linkedin_profile_read_ready_when_connected() -> None:
    intent = interpret_instruction("Show my LinkedIn profile")
    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations={"linkedin"},
        connected_credential_ids={"linkedin-read"},
        preferred_credential_by_integration={"linkedin": ("linkedin-read", "oauth_token")},
        credential_type_by_id={"linkedin-read": "oauth_token"},
    )
    assert selections[0].readiness == "ready"
    assert selections[0].credential_reference == {
        "credential_id": "linkedin-read",
        "credential_type": "oauth_token",
    }
    assert missing == []


def test_github_repo_read_language_and_input() -> None:
    intent = interpret_instruction("Read the GitHub repo https://github.com/acme/widgets")
    assert intent.requested_outcomes == ["read_github"]
    jobs = route_jobs_for_intent(intent)
    assert {j.job_key for j in jobs} == {"ops.github_repo_read"}
    payload = build_action_input(action_name="github.repo_read", intent=intent)
    assert payload["owner"] == "acme"
    assert payload["repo"] == "widgets"
    assert payload["ref"] is None


def test_google_contacts_read_is_not_crm_write() -> None:
    intent = interpret_instruction("List my Google Contacts")
    assert intent.requested_outcomes == ["read_contacts"]
    assert "update_crm" not in intent.requested_outcomes
    jobs = route_jobs_for_intent(intent)
    assert {j.job_key for j in jobs} == {"ops.google_contacts_read"}
    payload = build_action_input(action_name="google_contacts.people_list", intent=intent)
    assert payload["page_size"] == 100


def test_job_catalog_operator_reads_are_runtime_bound() -> None:
    linkedin = get_business_job("ops.linkedin_profile_read")
    github = get_business_job("ops.github_repo_read")
    contacts = get_business_job("ops.google_contacts_read")
    assert linkedin is not None and linkedin.maturity == "runtime_bound"
    assert github is not None and github.maturity == "runtime_bound"
    assert contacts is not None and contacts.maturity == "runtime_bound"
