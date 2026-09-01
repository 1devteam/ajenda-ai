from __future__ import annotations

import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_action_selection_adjudication import (  # noqa: E402
    REPO_ROOT,
    _resolver_catalog_drifts,
    adjudicate_runtime_action_selection,
)


def _report() -> dict[str, object]:
    return adjudicate_runtime_action_selection(build_graph(), repo_root=REPO_ROOT)


def _results() -> dict[str, dict[str, object]]:
    report = _report()
    return {str(item["finding_id"]): item for item in report["results"]}


def test_binding_disposition_is_preserved_while_selection_applicability_is_added() -> None:
    results = _results()

    primary = results["runtime-binding-gap:sales.research_context:sales.research:prospect_candidates"]
    crm = results["runtime-binding-gap:sales.research_context:crm.research:prospect_candidates"]

    assert primary["result"] == "SATISFIED"
    assert primary["binding_disposition"] == "CONSUMED_WHEN_APPLICABLE"
    assert primary["action_selection"]["normal_role"] == "primary"
    assert primary["action_selection"]["normal_position"] == 0
    assert primary["action_selection"]["decision"] == "requires_instantiated_resolver_state"

    assert crm["result"] == "SATISFIED"
    assert crm["binding_disposition"] == "CONSUMED_WHEN_APPLICABLE"
    assert crm["action_selection"]["normal_role"] == "fallback"
    assert crm["action_selection"]["normal_position"] == 1
    assert crm["action_selection"]["prior_actions"] == ["sales.research"]
    assert crm["action_selection"]["connection_hint"]["integration"] == "hubspot"

    assert (
        "runtime-binding-gap:sales.research_context:web.research:prospect_candidates"
        not in results
    )


def test_crm_pipeline_closure_is_primary_and_connection_conditioned() -> None:
    results = _results()
    for artifact in ("prospect_candidates", "qualified_prospects"):
        item = results[f"runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:{artifact}"]
        selection = item["action_selection"]
        assert item["result"] == "SATISFIED"
        assert item["binding_disposition"] == "CONSUMED_WHEN_APPLICABLE"
        assert selection["normal_role"] == "primary"
        assert selection["connection_hint"]["integration"] == "hubspot"
        assert "required connection is available" in selection["requirements"]
        assert selection["state"] == "conditional_on_resolver_selection"


def test_catalog_only_binding_controls_remain_inactive() -> None:
    results = _results()
    for finding_id in (
        "runtime-binding-gap:accounting.prepare_invoice_drafts:document.generate:revenue_records",
        "runtime-binding-gap:accounting.prepare_reconciliation:document.generate:revenue_records",
        "runtime-binding-gap:accounting.prepare_reconciliation:record.search:revenue_records",
    ):
        item = results[finding_id]
        assert item["result"] == "SATISFIED"
        assert item["action_selection"]["state"] == "inactive"


def test_current_sales_research_context_resolver_matches_catalog() -> None:
    report = _report()
    findings = {item["id"]: item for item in report["resolver_catalog_findings"]}

    assert "resolver-catalog-action-drift:sales.research_context:web.search" not in findings


def test_synthetic_drift_control_does_not_depend_on_graph_inventory_parser() -> None:
    drifts = _resolver_catalog_drifts(
        jobs={
            "synthetic.job": {
                "candidate_actions": ["synthetic.primary"],
                "maturity": "runtime_bound",
            }
        },
        preferences={"synthetic.job": ["synthetic.primary", "synthetic.rogue"]},
    )

    assert len(drifts) == 1
    assert drifts[0]["id"] == "resolver-catalog-action-drift:synthetic.job:synthetic.rogue"
    assert drifts[0]["normal_role"] == "fallback"


def test_selection_report_is_non_enforcing_and_preserves_binding_counts() -> None:
    report = _report()

    assert report["schema_version"] == "1.0"
    assert report["policy"]["enforcement"] == "disabled"
    assert report["policy"]["action_selection_instantiation"] == "required-for-enforcement"
    assert report["metrics"] == {
        "candidate_count": 8,
        "satisfied_count": 8,
        "violated_count": 0,
        "indeterminate_count": 0,
        "violated_primary_action_count": 0,
        "violated_fallback_action_count": 0,
        "unresolved_action_selection_count": 0,
        "resolver_catalog_drift_count": 0,
    }
