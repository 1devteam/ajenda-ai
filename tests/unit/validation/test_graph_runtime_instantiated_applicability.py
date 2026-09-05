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


@pytest.fixture(scope="module")
def graph() -> dict[str, object]:
    return build_graph()


def _report(graph: dict[str, object], context: dict[str, object]) -> dict[str, object]:
    return instantiate_runtime_contract_findings(graph, context, repo_root=REPO_ROOT)


def test_resolved_crm_and_sales_contracts_have_no_runtime_binding_findings(graph: dict[str, object]) -> None:
    report = _report(
        graph,
        {
            "selected_job_keys": ["sales.research_context", "crm.pipeline_maintenance"],
            "available_inputs": ["qualified_prospects"],
            "connected_integrations": ["hubspot"],
            "action_states": {
                "sales.research_context": {"sales.research": "ready"},
                "crm.pipeline_maintenance": {"gtm.crm_upsert": "ready"},
            },
        },
    )
    assert report["metrics"]["active_violation_count"] == 0
    assert report["metrics"]["instantiated_violated_count"] == 0
    assert not any(str(item["finding_id"]).startswith("runtime-binding-gap:") for item in report["results"])


def test_catalog_only_jobs_are_not_runtime_contract_findings(graph: dict[str, object]) -> None:
    report = _report(graph, {"selected_job_keys": ["vertical.ads.v1", "vertical.code.v1"]})
    assert report["metrics"]["active_violation_count"] == 0
    assert report["metrics"]["instantiated_violated_count"] == 0


def test_report_is_non_enforcing_and_authorizes_no_runtime_repair(graph: dict[str, object]) -> None:
    report = _report(graph, {})
    assert report["schema_version"] == "1.0"
    assert report["policy"]["enforcement"] == "disabled"
    assert report["policy"]["indeterminate"] == "non-enforceable"
    assert report["metrics"]["active_violation_count"] == 0
    assert report["metrics"]["instantiated_violated_count"] == 0
