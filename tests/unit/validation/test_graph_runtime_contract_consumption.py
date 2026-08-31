import ast
import sys
from pathlib import Path

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_contract_consumption import (  # noqa: E402
    REPO_ROOT,
    _function_consumption,
    adjudicate_runtime_contracts_with_consumption,
)


def _results() -> dict[str, dict[str, object]]:
    report = adjudicate_runtime_contracts_with_consumption(build_graph(), repo_root=REPO_ROOT)
    return {str(item["finding_id"]): item for item in report["results"]}


def test_real_controls_require_typed_behavioral_consumption() -> None:
    results = _results()

    email = results["runtime-binding-gap:email.deliver_outreach:gtm.email_send:introduction_drafts"]
    assert email["result"] == "SATISFIED"
    assert email["binding_disposition"] == "CONSUMED_WHEN_APPLICABLE"
    assert email["consumption"]["status"] == "consumed"
    assert any(
        evidence["function"] == "_specialize_email_send_input"
        for evidence in email["consumption"]["evidence"]
        if evidence["status"] == "consumed"
    )

    for finding_id in (
        "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:prospect_candidates",
        "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:qualified_prospects",
        "runtime-binding-gap:sales.research_context:crm.research:prospect_candidates",
        "runtime-binding-gap:sales.research_context:sales.research:prospect_candidates",
    ):
        item = results[finding_id]
        assert item["result"] == "VIOLATED"
        assert item["binding_disposition"] == "UNCONSUMED_WHEN_APPLICABLE"
        assert item["consumption"]["status"] == "unconsumed"


def test_existing_missing_and_schema_rejected_violations_remain_violations() -> None:
    results = _results()

    knowledge = results[
        "runtime-binding-gap:intelligence.retrieve_knowledge:knowledge.retrieve_current:observed_contacts"
    ]
    web = results["runtime-binding-gap:sales.research_context:web.research:prospect_candidates"]

    assert knowledge["result"] == "VIOLATED"
    assert knowledge["binding_disposition"] == "MISSING_WHEN_APPLICABLE"
    assert web["result"] == "VIOLATED"
    assert web["binding_disposition"] == "SCHEMA_REJECTED_WHEN_APPLICABLE"


def test_non_runtime_controls_remain_not_applicable() -> None:
    results = _results()
    for finding_id in (
        "runtime-binding-gap:accounting.prepare_invoice_drafts:document.generate:revenue_records",
        "runtime-binding-gap:accounting.prepare_reconciliation:document.generate:revenue_records",
        "runtime-binding-gap:accounting.prepare_reconciliation:record.search:revenue_records",
    ):
        item = results[finding_id]
        assert item["result"] == "SATISFIED"
        assert item["binding_disposition"] == "NOT_APPLICABLE"


def test_consumption_analyzer_distinguishes_read_escape_and_nonuse() -> None:
    consumed_tree = ast.parse(
        """
def handler(bound):
    context = bound.get('context') or {}
    return context.get('prospect_candidates')
"""
    )
    escaped_tree = ast.parse(
        """
def handler(bound):
    context = bound.get('context') or {}
    return consume(context)
"""
    )
    unused_tree = ast.parse(
        """
def handler(bound):
    context = bound.get('context') or {}
    return context.get('require_external_crm')
"""
    )

    target = ("context", "prospect_candidates")
    consumed = _function_consumption(
        function=consumed_tree.body[0],
        source="synthetic",
        target_path=target,
        explicit_roots={"bound"},
    )
    escaped = _function_consumption(
        function=escaped_tree.body[0],
        source="synthetic",
        target_path=target,
        explicit_roots={"bound"},
    )
    unused = _function_consumption(
        function=unused_tree.body[0],
        source="synthetic",
        target_path=target,
        explicit_roots={"bound"},
    )

    assert consumed.status == "consumed"
    assert escaped.status == "indeterminate"
    assert unused.status == "unconsumed"


def test_final_report_is_non_enforcing_and_closes_current_control_set() -> None:
    report = adjudicate_runtime_contracts_with_consumption(build_graph(), repo_root=REPO_ROOT)

    assert report["schema_version"] == "1.2"
    assert report["policy"]["enforcement"] == "disabled"
    assert report["policy"]["typed_consumption_required"] is True
    assert report["metrics"] == {
        "candidate_count": 10,
        "satisfied_count": 4,
        "violated_count": 6,
        "indeterminate_count": 0,
    }
