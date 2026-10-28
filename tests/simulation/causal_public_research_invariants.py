"""Deterministic causal simulations for public research correction review.

Run intentionally, not as ordinary CI:
    python -m pytest tests/simulation/causal_public_research_invariants.py -q

These tests assert the *desired* behavior, not the currently observed behavior.
Some must fail on the main-derived recovery baseline until their owners are repaired.
No network, browser, database, or CRM effects are executed by these scenarios.
A green run cannot replace full queue/lease/dispatcher and real provider proof.
"""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from backend.services.internet.contracts import PageSnapshot
from backend.services.internet.modes import InternetAccessMode
from backend.services.mission_composition.action_input_research import build_research_action_input
from backend.services.mission_composition.action_input_sales import build_sales_action_input
from backend.services.mission_composition.capability_resolver import route_jobs_for_intent
from backend.services.mission_composition.intent_interpreter import interpret_instruction
from backend.services.mission_composition.job_catalog import get_business_job
from backend.services.mission_composition.plan_compiler import _dependency_jobs_for_selection
from backend.services.tools.sales_action_qualification import sales_qualify
from backend.services.tools.schemas import ActionRuntimeContext, ToolInvocation
from backend.services.tools.web_action_contacts import research_observe_contacts

_MARKET_INSTRUCTION = (
    "Research three HVAC companies in Dallas using public sources only, "
    "qualify the companies, and do not send messages."
)


def _context() -> ActionRuntimeContext:
    return ActionRuntimeContext(
        tenant_id="tenant-simulation",
        task_id=uuid4(),
        mission_id=uuid4(),
        worker_id="simulation-worker",
        lease_id="simulation-lease",
    )


def _snapshot(*, text: str, url: str = "https://quiet-hvac.example/") -> PageSnapshot:
    return PageSnapshot(
        url=url,
        real=True,
        status_code=200,
        title="Quiet HVAC" if "quiet-hvac.example" in url else "HVAC options",
        text_preview=text,
        body_preview="",
        access_mode=InternetAccessMode.PAGE_READ,
    )


def _observe(*, snapshot: PageSnapshot, company: str, collect_contacts: bool = True):
    invocation = ToolInvocation(
        action="research.observe_contacts",
        input={
            "prospects": [
                {
                    "company": company,
                    "domain": snapshot.url.split("/")[2],
                    "url": snapshot.url,
                    "website": snapshot.url,
                }
            ],
            "requested_quantity": 1,
            "binding_required": True,
            "collect_contacts": collect_contacts,
            "context": {"industry": "HVAC", "location": "Dallas"},
        },
    )
    with patch(
        "backend.services.tools.web_action_contacts.fetch_public_page",
        return_value=snapshot,
    ):
        return research_observe_contacts(invocation, _context())


@pytest.mark.parametrize(
    ("contact_text", "expected_count"),
    [
        ("Quiet HVAC provides heating and cooling in Dallas.", 0),
        ("Quiet HVAC provides heating and cooling in Dallas. service@quiet-hvac.example", 1),
    ],
    ids=["verified-page-without-contact", "verified-page-with-actual-email"],
)
def test_contact_acceptance_requires_actual_values(contact_text: str, expected_count: int) -> None:
    """A company may be verified without completing a contact objective."""
    result = _observe(snapshot=_snapshot(text=contact_text), company="Quiet HVAC")
    output = result.output

    assert len(output["verified_prospect_candidates"]) == 1
    assert output["observed_count"] == expected_count
    assert output["contact_value_count"] == expected_count
    assert output["accept_met"] is (expected_count == 1)
    assert len(output["observed_contacts"]) == expected_count
    assert len(output["condition_observations"]) == expected_count
    assert all(
        item.get("kind") in {"email", "phone"} and str(item.get("value") or "").strip()
        for item in output["observed_contacts"]
    )


def test_generic_market_landing_page_cannot_verify_an_unrelated_company() -> None:
    """Host matching its own search result does not establish company ownership."""
    snapshot = _snapshot(
        url="https://leadlanding.example/",
        text="Compare HVAC heating and cooling services offered across Dallas.",
    )
    result = _observe(snapshot=snapshot, company="Quiet HVAC", collect_contacts=False)
    assert result.output["verified_prospect_candidates"] == []
    assert result.output["prospect_candidates"][0]["identity_status"] == "unverified"


def test_market_scope_does_not_populate_named_company_target() -> None:
    """Market category HVAC must not become a named company."""
    intent = interpret_instruction(_MARKET_INSTRUCTION)
    assert "research_prospects" in intent.requested_outcomes
    result = build_research_action_input(action_name="web.research", intent=intent)
    assert result is not None
    assert "HVAC" in result["query"]
    assert result["company"] is None


def test_composed_empty_input_never_scores_a_synthetic_market_company() -> None:
    """Even a directly invoked handler cannot materialize its planning-only seed."""
    intent = interpret_instruction(_MARKET_INSTRUCTION)
    payload = build_sales_action_input(action_name="sales.qualify", intent=intent)
    assert payload is not None
    assert payload["prospects"] == []
    try:
        result = sales_qualify(
            ToolInvocation(action="sales.qualify", input=payload),
            _context(),
        )
    except ValueError:
        # A missing-required-world-state exception is an acceptable fail-closed
        # result here; validated terminal-empty semantics are tested separately.
        return
    assert result.output["scored_prospects"] == []
    assert result.output["qualified_prospects"] == []


def test_real_company_does_not_inherit_market_target_fields_from_seed() -> None:
    """Planning industry/location must remain constraints, not observed company facts."""
    intent = interpret_instruction(_MARKET_INSTRUCTION)
    payload = build_sales_action_input(action_name="sales.qualify", intent=intent)
    assert payload is not None
    payload["prospects"] = [
        {
            "prospect_id": "web:quiet",
            "company": "Quiet HVAC",
            "source": "public_search",
            "domain": "quiet-hvac.example",
            "website": "https://quiet-hvac.example/",
            "identity_status": "verified",
            "identity_evidence_urls": ["https://quiet-hvac.example/"],
        }
    ]
    result = sales_qualify(ToolInvocation(action="sales.qualify", input=payload), _context())
    row = result.output["scored_prospects"][0]
    assert row["company"] == "Quiet HVAC"
    assert row.get("industry") is None
    assert row.get("location") is None
    assert row.get("intent") is None
    assert row.get("source") == "public_search"


def test_public_qualification_graph_consumes_verifier_not_implicit_contacts() -> None:
    """A selected verifier must actually be upstream of qualification."""
    intent = interpret_instruction(_MARKET_INSTRUCTION)
    jobs = route_jobs_for_intent(intent)
    selected = {job.job_key for job in jobs}
    assert "research.verify_public_candidates" in selected

    qualification = get_business_job("sales.qualify_prospects")
    dependencies = _dependency_jobs_for_selection(job=qualification, selected_keys=selected, intent=intent)
    assert "research.verify_public_candidates" in dependencies
    assert "research.observe_sources" not in dependencies


def test_direct_explicit_lead_remains_supported_as_positive_control() -> None:
    """A composed public-market fix must not globally ban direct supplied leads."""
    result = sales_qualify(
        ToolInvocation(
            action="sales.qualify",
            input={
                "lead": {"company": "Named Partner", "email": "owner@partner.example"},
                "context": {},
            },
        ),
        _context(),
    )
    assert result.output["scored_prospects"][0]["company"] == "Named Partner"


def test_missing_contact_propagates_to_mission_acceptance_reasons() -> None:
    """Simulate handler output -> durable task -> mission contact acceptance."""
    from backend.domain.enums import ExecutionTaskState
    from backend.domain.execution_task import ExecutionTask
    from backend.services.worker_runtime_contracts import _observe_acceptance_reasons

    result = _observe(
        snapshot=_snapshot(text="Quiet HVAC provides cooling in Dallas."),
        company="Quiet HVAC",
    )
    completed = ExecutionTask(
        id=uuid4(),
        tenant_id="tenant-simulation",
        mission_id=uuid4(),
        title="Observed company website",
        description="Observed page without usable contact information",
        status=ExecutionTaskState.COMPLETED.value,
        metadata_json={
            "tool_invocation": {"action": "research.observe_contacts"},
            "handler_result": {"output": result.output},
        },
    )
    reasons = _observe_acceptance_reasons([completed], require_contacts=True)
    assert reasons
    assert "produced 0" in reasons[0]


def test_intermediate_discovery_never_materializes_raw_public_identity() -> None:
    """Positive control: preserve the existing intermediate source boundary."""
    from backend.domain.enums import ExecutionTaskState
    from backend.domain.execution_task import ExecutionTask
    from backend.services.mission_composition.deliverable_runtime_artifacts import (
        materialized_artifact_for_task,
    )

    completed = ExecutionTask(
        id=uuid4(),
        tenant_id="tenant-simulation",
        mission_id=uuid4(),
        title="Public search",
        description="Search result remains unverified",
        status=ExecutionTaskState.COMPLETED.value,
        metadata_json={
            "expected_output_contract": {
                "artifact": "prospect_candidates",
                "materialization_role": "intermediate",
                "allow_empty": True,
            },
            "handler_result": {
                "output": {
                    "prospect_candidates": [
                        {
                            "company": "HVAC Listing",
                            "source": "public_search",
                            "real": False,
                            "identity_status": "unverified",
                            "website": "https://leadlanding.example/",
                        }
                    ]
                }
            },
        },
    )
    assert materialized_artifact_for_task(completed) is None
