from pathlib import Path
import sys

VALIDATION_DIR = Path(__file__).resolve().parents[3] / "scripts" / "validation"
if str(VALIDATION_DIR) not in sys.path:
    sys.path.insert(0, str(VALIDATION_DIR))

from build_dependency_graph import build_graph  # noqa: E402
from graph_runtime_contract_adjudication import (  # noqa: E402
    REPO_ROOT,
    adjudicate_runtime_binding_candidates,
    compiler_binding_path,
)


def _results() -> dict[str, dict[str, object]]:
    report = adjudicate_runtime_binding_candidates(build_graph(), repo_root=REPO_ROOT)
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

    assert results[
        "runtime-binding-gap:intelligence.retrieve_knowledge:knowledge.retrieve_current:observed_contacts"
    ]["result"] == "VIOLATED"
    assert results[
        "runtime-binding-gap:sales.research_context:web.research:prospect_candidates"
    ]["result"] == "VIOLATED"

    for finding_id in (
        "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:prospect_candidates",
        "runtime-binding-gap:crm.pipeline_maintenance:gtm.crm_upsert:qualified_prospects",
        "runtime-binding-gap:email.deliver_outreach:gtm.email_send:introduction_drafts",
        "runtime-binding-gap:sales.research_context:crm.research:prospect_candidates",
        "runtime-binding-gap:sales.research_context:sales.research:prospect_candidates",
    ):
        assert results[finding_id]["result"] == "SATISFIED"


def test_catalog_only_jobs_do_not_create_runtime_binding_violations() -> None:
    results = _results()
    for finding_id in (
        "runtime-binding-gap:accounting.prepare_invoice_drafts:document.generate:revenue_records",
        "runtime-binding-gap:accounting.prepare_reconciliation:document.generate:revenue_records",
        "runtime-binding-gap:accounting.prepare_reconciliation:record.search:revenue_records",
    ):
        assert results[finding_id]["result"] == "SATISFIED"
        assert results[finding_id]["applicability"] is False


def test_adjudication_remains_non_enforcing_and_complete_for_current_controls() -> None:
    report = adjudicate_runtime_binding_candidates(build_graph(), repo_root=REPO_ROOT)

    assert report["policy"]["enforcement"] == "disabled"
    assert report["metrics"] == {
        "candidate_count": 10,
        "satisfied_count": 8,
        "violated_count": 2,
        "indeterminate_count": 0,
    }
