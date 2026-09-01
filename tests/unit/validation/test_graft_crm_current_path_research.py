from __future__ import annotations

import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_instantiated_applicability import (  # noqa: E402
    REPO_ROOT,
    instantiate_runtime_contract_findings,
)

from backend.services.mission_composition.capability_resolver import (  # noqa: E402
    _intent_input_sources,
    resolve_jobs,
    route_jobs_for_intent,
)
from backend.services.mission_composition.intent_interpreter import interpret_instruction  # noqa: E402
from backend.services.operating_charter import default_operating_charter  # noqa: E402

CRM_PROSPECT = "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:prospect_candidates"
CRM_QUALIFIED = "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:qualified_prospects"


def test_current_update_crm_path_instantiates_both_crm_graft_violations() -> None:
    """Disposable research witness: derive G.R.A.F.T. context from current Ajenda source behavior."""

    intent = interpret_instruction("Find three roofing companies in Austin and add them to contacts")
    jobs = route_jobs_for_intent(intent)
    selections, _ = resolve_jobs(
        jobs,
        intent=intent,
        charter=default_operating_charter(),
        connected_integrations={"hubspot"},
    )

    selected = [item for item in selections if item.selection_status == "selected" and item.readiness == "ready"]
    context = {
        "selected_job_keys": sorted(job.job_key for job in jobs),
        "available_inputs": sorted(_intent_input_sources(intent)),
        "selected_actions": {item.job_key: item.action_name for item in selected},
        "connected_integrations": ["hubspot"],
    }

    report = instantiate_runtime_contract_findings(build_graph(), context, repo_root=REPO_ROOT)
    results = {str(item["finding_id"]): item for item in report["results"]}

    assert "crm.pipeline_maintenance" in context["selected_job_keys"]
    assert context["selected_actions"]["crm.pipeline_maintenance"] == "gtm.crm_upsert"
    assert "named_company" not in context["available_inputs"]
    assert "crm_record" not in context["available_inputs"]

    for finding_id in (CRM_PROSPECT, CRM_QUALIFIED):
        item = results[finding_id]
        assert item["static_result"] == "VIOLATED"
        assert item["instantiated_applicability"] == "ACTIVE"
        assert item["instantiated_result"] == "VIOLATED"
        assert item["repair_authorized"] is True
        assert item["instantiated_witness"]["job_selection"]["state"] == "SELECTED"
        assert item["instantiated_witness"]["dependency_applicability"]["state"] == "ACTIVE"
        assert item["instantiated_witness"]["action_selection"]["selected_action"] == "gtm.crm_upsert"
