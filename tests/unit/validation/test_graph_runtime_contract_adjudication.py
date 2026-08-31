import sys
from copy import deepcopy
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_contract_adjudication import (  # noqa: E402
    REPO_ROOT,
    adjudicate_runtime_binding_candidates,
    compiler_binding_path,
)


def _report() -> dict[str, object]:
    return adjudicate_runtime_binding_candidates(build_graph(), repo_root=REPO_ROOT)


def _results() -> dict[str, dict[str, object]]:
    report = _report()
    return {str(item["finding_id"]): item for item in report["results"]}


def test_compiler_binding_witnesses_are_source_derived() -> None:
    email = compiler_binding_path(
        repo_root=REPO_ROOT,
        action_name="gtm.email_send",
        artifact="introduction_drafts",
    )
    knowledge = compiler_binding_path(
        repo_root=REPO_ROOT,
        action_name="knowledge.retrieve_current",
        artifact="observed_contacts",
    )
    web_research = compiler_binding_path(
        repo_root=REPO_ROOT,
        action_name="web.research",
        artifact="prospect_candidates",
    )

    assert email.resolved is True
    assert email.path == "$.input.context.introduction_drafts"
    assert knowledge.resolved is True
    assert knowledge.path is None
    assert web_research.resolved is True
    assert web_research.path == "$.input.context.prospect_candidates"


def test_current_binding_candidates_are_self_adjudicated() -> None:
    results = _results()

    knowledge = results[
        "runtime-binding-gap:intelligence.retrieve_knowledge:knowledge.retrieve_current:observed_contacts"
    ]
    assert knowledge["result"] == "VIOLATED"
    assert knowledge["binding_disposition"] == "MISSING_WHEN_APPLICABLE"
    assert knowledge["applicability"]["state"] == "always_when_job_selected"

    web = results[
        "runtime-binding-gap:sales.research_context:web.research:prospect_candidates"
    ]
    assert web["result"] == "VIOLATED"
    assert web["binding_disposition"] == "SCHEMA_REJECTED_WHEN_APPLICABLE"
    assert web["applicability"]["state"] == "conditional"
    assert web["applicability"]["decision"] == "requires_instantiated_inputs"

    for finding_id in (
        "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:prospect_candidates",
        "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:qualified_prospects",
        "runtime-binding-gap:email.deliver_outreach:gtm.email_send:introduction_drafts",
        "runtime-binding-gap:sales.research_context:crm.research:prospect_candidates",
        "runtime-binding-gap:sales.research_context:sales.research:prospect_candidates",
    ):
        assert results[finding_id]["result"] == "SATISFIED"
        assert results[finding_id]["binding_disposition"] == "COMPATIBLE_WHEN_APPLICABLE"


def test_conditional_results_preserve_predicates_without_claiming_activation() -> None:
    results = _results()
    crm = results[
        "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:prospect_candidates"
    ]

    assert crm["applicability"] == {
        "state": "conditional",
        "decision": "requires_instantiated_inputs",
        "dependency_kind": "conditional",
        "required_when_missing": ["prospect_candidates", "qualified_prospects"],
        "satisfied_by": ["named_company", "crm_record"],
        "reason": "activation depends on the instantiated intent/world-state satisfiers",
    }


def test_catalog_only_jobs_do_not_create_runtime_binding_violations() -> None:
    results = _results()
    for finding_id in (
        "runtime-binding-gap:accounting.prepare_invoice_drafts:document.generate:revenue_records",
        "runtime-binding-gap:accounting.prepare_reconciliation:document.generate:revenue_records",
        "runtime-binding-gap:accounting.prepare_reconciliation:record.search:revenue_records",
    ):
        assert results[finding_id]["result"] == "SATISFIED"
        assert results[finding_id]["binding_disposition"] == "NOT_APPLICABLE"
        assert results[finding_id]["applicability"]["state"] == "inactive"


def test_plan_time_binding_cannot_be_masked_by_runtime_fallback() -> None:
    graph = deepcopy(build_graph())
    graph["edges"].append(
        {
            "from": "action:web.research",
            "to": "artifact:prospect_candidates",
            "type": "binds_artifact",
            "evidence": "synthetic-fallback-control",
            "output_path": "$.prospect_candidates",
            "input_path": "$.input.query",
        }
    )

    report = adjudicate_runtime_binding_candidates(graph, repo_root=REPO_ROOT)
    results = {str(item["finding_id"]): item for item in report["results"]}
    web = results[
        "runtime-binding-gap:sales.research_context:web.research:prospect_candidates"
    ]

    assert web["result"] == "VIOLATED"
    assert web["binding"]["phase"] == "plan_compile"
    assert web["binding"]["input_path"] == "$.input.context.prospect_candidates"
    assert web["binding"]["runtime_fallback"]["input_path"] == "$.input.query"


def test_unknown_action_schema_fails_to_indeterminate_not_violation() -> None:
    graph = deepcopy(build_graph())
    graph["nodes"].extend(
        [
            {
                "id": "job:synthetic.producer",
                "type": "business_job",
                "label": "Synthetic producer",
                "job_key": "synthetic.producer",
                "maturity": "runtime_bound",
            },
            {
                "id": "job:synthetic.consumer",
                "type": "business_job",
                "label": "Synthetic consumer",
                "job_key": "synthetic.consumer",
                "maturity": "runtime_bound",
            },
            {
                "id": "artifact:synthetic_artifact",
                "type": "runtime_artifact",
                "label": "synthetic_artifact",
                "producers": ["synthetic.producer"],
            },
            {
                "id": "action:synthetic.unknown",
                "type": "runtime_action",
                "label": "synthetic.unknown",
            },
        ]
    )
    graph["edges"].append(
        {
            "from": "job:synthetic.consumer",
            "to": "job:synthetic.producer",
            "type": "depends_on_hard",
            "evidence": "synthetic-control",
        }
    )
    graph["semantic_findings"].append(
        {
            "id": "runtime-binding-gap:synthetic.consumer:synthetic.unknown:synthetic_artifact",
            "classification": "binding_coverage_gap",
            "evidence": ["synthetic-control"],
            "related_nodes": [
                "job:synthetic.consumer",
                "action:synthetic.unknown",
                "artifact:synthetic_artifact",
            ],
        }
    )

    report = adjudicate_runtime_binding_candidates(graph, repo_root=REPO_ROOT)
    synthetic = next(
        item
        for item in report["results"]
        if item["finding_id"]
        == "runtime-binding-gap:synthetic.consumer:synthetic.unknown:synthetic_artifact"
    )

    assert synthetic["result"] == "INDETERMINATE"
    assert synthetic["binding_disposition"] == "UNRESOLVED"
    assert synthetic["schema"]["status"] == "indeterminate"


def test_adjudication_remains_non_enforcing_and_complete_for_current_controls() -> None:
    report = _report()

    assert report["schema_version"] == "1.1"
    assert report["policy"]["enforcement"] == "disabled"
    assert report["policy"]["applicability_instantiation"] == "required-for-conditional-enforcement"
    assert report["metrics"] == {
        "candidate_count": 10,
        "satisfied_count": 8,
        "violated_count": 2,
        "indeterminate_count": 0,
    }
