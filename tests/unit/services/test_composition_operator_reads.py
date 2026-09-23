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
    MissionIntent,
    TargetEntity,
)
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.job_catalog import get_business_job
from backend.services.operating_charter import default_operating_charter


def test_versions_bumped_for_wave_a() -> None:
    assert JOB_CATALOG_VERSION == "12"
    assert INTERPRETER_VERSION == "14"
    assert CAPABILITY_RESOLVER_VERSION == "11"


def test_web_page_observation_selects_browser_only_for_explicit_url() -> None:
    intent = MissionIntent(
        objective="Observe the target web page",
        requested_outcomes=["observe_web_page"],
        target_entities=[TargetEntity(type="web_page", url="https://example.com")],
    )
    jobs = route_jobs_for_intent(intent)
    assert {job.job_key for job in jobs} == {"research.observe_web_page"}
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations=set(),
    )
    assert not missing
    assert selections[0].action_name == "web.browser_session"
    assert selections[0].readiness == "ready"


def test_web_page_observation_declares_complete_evidence_contract() -> None:
    job = get_business_job("research.observe_web_page")

    assert job.evidence_requirements == (
        "browser_step_trace",
        "source_url",
        "final_url",
        "extracted_observations",
        "observation_timestamp",
        "blocked_requests",
        "observation_satisfied",
    )


def test_web_page_observation_rejects_missing_url() -> None:
    intent = MissionIntent(objective="Observe a web page", requested_outcomes=["observe_web_page"])
    jobs = route_jobs_for_intent(intent)
    selections, _ = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations=set(),
    )
    assert selections[0].readiness == "unavailable"
    assert "explicit target URL" in selections[0].selection_reason


def test_public_identity_verification_selects_governed_read_action() -> None:
    intent = MissionIntent(
        objective="Verify the public identity of Acme HVAC",
        requested_outcomes=["verify_public_identity"],
        target_entities=[
            TargetEntity(
                type="company",
                attributes={
                    "url": "https://acmehvac.example",
                    "expected_company": "Acme HVAC",
                    "industry": "HVAC",
                    "location": "Dallas",
                },
            )
        ],
    )
    jobs = route_jobs_for_intent(intent)
    assert {job.job_key for job in jobs} == {"research.verify_public_identity"}
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations=set(),
    )
    assert not missing
    assert selections[0].action_name == "research.verify_public_identity"
    assert selections[0].readiness == "ready"


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
    assert selections[0].action_name == "linkedin.profile_read"
    assert not missing


def test_linkedin_publish_does_not_become_profile_read() -> None:
    intent = interpret_instruction("Post an update to LinkedIn about our launch")
    assert "read_linkedin" not in intent.requested_outcomes
    assert "publish_content" in intent.requested_outcomes


def test_github_repo_read_composes_with_owner_repo() -> None:
    intent = interpret_instruction("Read the GitHub repo 1devteam/ajenda-ai")
    assert "read_github" in intent.requested_outcomes
    assert intent.ambiguity == []
    jobs = route_jobs_for_intent(intent)
    assert {j.job_key for j in jobs} == {"ops.github_repo_read"}
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations=set(),
    )
    assert selections[0].action_name == "github.repo_read"
    assert selections[0].readiness == "connection_required"
    assert selections[0].connection_provider == "github"
    assert missing and missing[0]["provider"] == "github"
    payload = build_action_input(action_name="github.repo_read", intent=intent)
    assert payload["owner"] == "1devteam"
    assert payload["repo"] == "ajenda-ai"


def test_github_repo_read_ready_when_connected() -> None:
    intent = interpret_instruction("Check the github repository octocat/Hello-World")
    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations={"github"},
        connected_credential_ids={"github-read"},
        preferred_credential_by_integration={"github": ("github-read", "oauth_token")},
        credential_type_by_id={"github-read": "oauth_token"},
    )
    assert selections[0].readiness == "ready"
    assert not missing


def test_google_contacts_read_composes_to_connection_required() -> None:
    intent = interpret_instruction("List my Google Contacts")
    assert intent.requested_outcomes == ["read_contacts"]
    assert intent.ambiguity == []
    jobs = route_jobs_for_intent(intent)
    assert {j.job_key for j in jobs} == {"ops.google_contacts_read"}
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations=set(),
    )
    assert selections[0].action_name == "provider.external_read"
    assert selections[0].readiness == "connection_required"
    assert selections[0].connection_provider == "google_contacts"
    assert missing and missing[0]["provider"] == "google_contacts"
    payload = build_action_input(action_name="provider.external_read", intent=intent)
    assert "people.googleapis.com" in payload["url"]
    assert payload["method"] == "GET"


def test_google_contacts_read_ready_when_connected() -> None:
    intent = interpret_instruction("Read my google contacts")
    jobs = route_jobs_for_intent(intent)
    selections, missing = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations={"google_contacts"},
        connected_credential_ids={"google-contacts-read"},
        preferred_credential_by_integration={"google_contacts": ("google-contacts-read", "oauth_token")},
        credential_type_by_id={"google-contacts-read": "oauth_token"},
    )
    assert selections[0].readiness == "ready"
    assert not missing


def test_add_to_contacts_still_update_crm_not_contacts_read() -> None:
    intent = interpret_instruction("Find three roofing companies in Austin and add them to contacts")
    assert "update_crm" in intent.requested_outcomes
    assert "read_contacts" not in intent.requested_outcomes


def test_return_contact_info_does_not_select_google_contacts() -> None:
    intent = interpret_instruction("Open https://example.com and return the contact info")
    assert "observe_contacts" in intent.requested_outcomes
    assert "read_contacts" not in intent.requested_outcomes


def test_negated_contact_anyone_does_not_select_google_contacts() -> None:
    intent = interpret_instruction(
        "Research five competitors using public sources only. Do not contact anyone or modify external systems."
    )

    assert "research_prospects" in intent.requested_outcomes
    assert "read_contacts" not in intent.requested_outcomes
    assert "ops.google_contacts_read" not in {job.job_key for job in route_jobs_for_intent(intent)}


def test_wave_a_jobs_are_runtime_bound() -> None:
    for key in (
        "ops.linkedin_profile_read",
        "ops.github_repo_read",
        "ops.google_contacts_read",
    ):
        job = get_business_job(key)
        assert job.maturity == "runtime_bound"
        assert job.credential_policy == "required"
