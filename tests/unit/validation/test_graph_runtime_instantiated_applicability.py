from __future__ import annotations

import sys
from pathlib import Path

import pytest

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_instantiated_applicability import (  # noqa: E402
    REPO_ROOT,
    instantiate_runtime_contract_findings,
)

SALES_PRIMARY = "runtime-binding-gap:sales.research_context:sales.research:prospect_candidates"
SALES_CRM = "runtime-binding-gap:sales.research_context:crm.research:prospect_candidates"
SALES_WEB = "runtime-binding-gap:sales.research_context:web.research:prospect_candidates"
CRM_PROSPECT = "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:prospect_candidates"


@pytest.fixture(scope="module")
def graph() -> dict[str, object]:
    return build_graph()


def _report(graph: dict[str, object], context: dict[str, object]) -> dict[str, object]:
    return instantiate_runtime_contract_findings(graph, context, repo_root=REPO_ROOT)


def _results(report: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(item["finding_id"]): item for item in report["results"]}


def test_c1_unselected_job_does_not_activate_static_violation(graph: dict[str, object]) -> None:
    item = _results(_report(graph, {"selected_job_keys": [], "available_inputs": []}))[SALES_PRIMARY]

    assert item["static_result"] == "VIOLATED"
    assert item["instantiated_result"] == "INDETERMINATE"
    assert item["instantiated_applicability"] == "NOT_APPLICABLE"
    assert item["repair_authorized"] is False


def test_c2_unknown_prior_candidate_keeps_fallback_indeterminate(graph: dict[str, object]) -> None:
    context = {
        "selected_job_keys": ["sales.research_context"],
        "available_inputs": [],
        "action_states": {"sales.research_context": {"crm.research": "ready"}},
        "connected_integrations": ["hubspot"],
    }
    item = _results(_report(graph, context))[SALES_CRM]

    assert item["instantiated_result"] == "INDETERMINATE"
    selection = item["instantiated_witness"]["action_selection"]
    assert selection["state"] == "INDETERMINATE"
    assert selection["evidence"][0]["action"] == "sales.research"
    assert selection["evidence"][0]["state"] == "unknown"


def test_c3_primary_ready_prevents_fallback_activation(graph: dict[str, object]) -> None:
    context = {
        "selected_job_keys": ["sales.research_context"],
        "available_inputs": [],
        "action_states": {"sales.research_context": {"sales.research": "ready", "crm.research": "ready"}},
        "connected_integrations": ["hubspot"],
    }
    results = _results(_report(graph, context))

    assert results[SALES_PRIMARY]["instantiated_result"] == "VIOLATED"
    assert results[SALES_PRIMARY]["repair_authorized"] is True
    assert results[SALES_CRM]["instantiated_result"] == "INDETERMINATE"
    assert results[SALES_CRM]["instantiated_applicability"] == "NOT_APPLICABLE"


def test_c4_rejected_primary_and_ready_fallback_selects_fallback(graph: dict[str, object]) -> None:
    context = {
        "selected_job_keys": ["sales.research_context"],
        "available_inputs": [],
        "action_states": {
            "sales.research_context": {
                "sales.research": "rejected",
                "crm.research": "ready",
            }
        },
        "connected_integrations": ["hubspot"],
    }
    item = _results(_report(graph, context))[SALES_CRM]

    assert item["instantiated_result"] == "VIOLATED"
    assert item["instantiated_applicability"] == "ACTIVE"
    assert item["repair_authorized"] is True
    assert item["instantiated_witness"]["action_selection"]["selected_action"] == "crm.research"


def test_c5_alternate_satisfier_deactivates_conditional_dependency(graph: dict[str, object]) -> None:
    context = {
        "selected_job_keys": ["sales.research_context"],
        "available_inputs": ["explicit_recipient"],
        "action_states": {"sales.research_context": {"sales.research": "ready"}},
    }
    item = _results(_report(graph, context))[SALES_PRIMARY]

    assert item["instantiated_result"] == "INDETERMINATE"
    dependency = item["instantiated_witness"]["dependency_applicability"]
    assert dependency["state"] == "NOT_APPLICABLE"
    assert dependency["matched_satisfiers"] == ["explicit_recipient"]
    assert item["repair_authorized"] is False


def test_c6_missing_required_input_activates_conditional_dependency(graph: dict[str, object]) -> None:
    context = {
        "selected_job_keys": ["sales.research_context"],
        "available_inputs": [],
        "action_states": {"sales.research_context": {"sales.research": "ready"}},
    }
    item = _results(_report(graph, context))[SALES_PRIMARY]

    assert item["instantiated_witness"]["dependency_applicability"]["state"] == "ACTIVE"
    assert item["instantiated_result"] == "VIOLATED"
    assert item["repair_authorized"] is True


def test_c7_unknown_satisfier_state_remains_indeterminate(graph: dict[str, object]) -> None:
    context = {
        "selected_job_keys": ["sales.research_context"],
        "action_states": {"sales.research_context": {"sales.research": "ready"}},
    }
    item = _results(_report(graph, context))[SALES_PRIMARY]

    assert item["instantiated_result"] == "INDETERMINATE"
    assert "dependency_applicability" in item["instantiated_witness"]["unresolved_predicates"]


def test_c8_connection_constrained_action_requires_connection_evidence(graph: dict[str, object]) -> None:
    base_context = {
        "selected_job_keys": ["crm.pipeline_maintenance"],
        "available_inputs": [],
        "action_states": {"crm.pipeline_maintenance": {"gtm.crm_upsert": "ready"}},
    }
    missing = _results(_report(graph, base_context))[CRM_PROSPECT]
    connected = _results(_report(graph, {**base_context, "connected_integrations": ["hubspot"]}))[CRM_PROSPECT]

    assert missing["instantiated_result"] == "INDETERMINATE"
    assert missing["repair_authorized"] is False
    assert connected["instantiated_result"] == "VIOLATED"
    assert connected["repair_authorized"] is True


def test_c9_static_disposition_is_preserved_when_instance_is_not_applicable(graph: dict[str, object]) -> None:
    context = {
        "selected_job_keys": ["sales.research_context"],
        "available_inputs": [],
        "action_states": {"sales.research_context": {"sales.research": "ready"}},
    }
    item = _results(_report(graph, context))[SALES_WEB]

    assert item["static_result"] == "VIOLATED"
    assert item["binding_disposition"] == "SCHEMA_REJECTED_WHEN_APPLICABLE"
    assert item["instantiated_result"] == "INDETERMINATE"
    assert item["instantiated_applicability"] == "NOT_APPLICABLE"


def test_c10_action_observation_alone_does_not_prove_business_job_identity(graph: dict[str, object]) -> None:
    item = _results(_report(graph, {"observed_actions": ["sales.research"]}))[SALES_PRIMARY]

    assert item["instantiated_result"] == "INDETERMINATE"
    assert item["instantiated_witness"]["job_selection"]["state"] == "INDETERMINATE"
    assert "business_job_selection" in item["instantiated_witness"]["unresolved_predicates"]
    assert item["instantiated_witness"]["observed_actions"] == ["sales.research"]


def test_direct_selected_action_still_requires_connection_state(graph: dict[str, object]) -> None:
    context = {
        "selected_job_keys": ["crm.pipeline_maintenance"],
        "available_inputs": [],
        "selected_actions": {"crm.pipeline_maintenance": "gtm.crm_upsert"},
    }
    unresolved = _results(_report(graph, context))[CRM_PROSPECT]
    resolved = _results(_report(graph, {**context, "connected_credential_ids": ["hubspot-crm"]}))[CRM_PROSPECT]

    assert unresolved["instantiated_result"] == "INDETERMINATE"
    assert resolved["instantiated_result"] == "VIOLATED"
    assert resolved["repair_authorized"] is True


def test_report_is_non_enforcing_and_generic_context_authorizes_no_runtime_repair(graph: dict[str, object]) -> None:
    report = _report(graph, {})

    assert report["schema_version"] == "1.0"
    assert report["graph_schema_version"] == "1.4"
    assert report["policy"]["enforcement"] == "disabled"
    assert report["policy"]["indeterminate"] == "non-enforceable"
    assert report["policy"]["action_name_observation_proves_job_identity"] is False
    assert report["metrics"]["active_violation_count"] == 0
    assert report["metrics"]["instantiated_violated_count"] == 0
