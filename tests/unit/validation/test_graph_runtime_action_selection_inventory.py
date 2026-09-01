from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts/validation/graph_runtime_action_selection_inventory.py"
SPEC = importlib.util.spec_from_file_location("ajenda_graph_runtime_action_selection_inventory", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _inventory() -> dict[str, object]:
    return MODULE.collect_runtime_action_selection_inventory(REPO_ROOT)


def test_inventory_preserves_catalog_and_resolver_as_distinct_authorities() -> None:
    inventory = _inventory()
    nodes = {node["id"]: node for node in inventory["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in inventory["edges"]}

    sales = nodes["selection:sales.research_context:sales.research"]
    crm = nodes["selection:sales.research_context:crm.research"]
    web = nodes["selection:sales.research_context:web.research"]
    web_search = nodes["selection:sales.research_context:web.search"]

    assert sales["normal_position"] == 0
    assert sales["normal_role"] == "primary"
    assert crm["normal_position"] == 1
    assert crm["normal_role"] == "fallback"
    assert crm["prior_actions"] == ["sales.research"]
    assert web["normal_position"] == 2
    assert web["prior_actions"] == ["sales.research", "crm.research"]
    assert web_search["normal_position"] == 3
    assert web_search["catalog_declared"] is False

    assert (
        "job:sales.research_context",
        "selection:sales.research_context:web.search",
        "resolver_selection",
    ) in edges
    assert (
        "selection:sales.research_context:web.search",
        "action:web.search",
        "selects_action",
    ) in edges


def test_inventory_surfaces_resolver_catalog_action_drift() -> None:
    inventory = _inventory()
    findings = {finding["id"]: finding for finding in inventory["findings"]}

    drift = findings["resolver-catalog-action-drift:sales.research_context:web.search"]
    assert drift["classification"] == "resolver_catalog_action_drift"
    assert drift["blocking"] is False
    assert drift["related_nodes"] == [
        "job:sales.research_context",
        "selection:sales.research_context:web.search",
        "action:web.search",
    ]
    assert inventory["metrics"]["resolver_only_pair_count"] == 1


def test_inventory_preserves_source_specific_selection_override() -> None:
    inventory = _inventory()
    nodes = {node["id"]: node for node in inventory["nodes"]}

    web = nodes["selection:research.discover_prospects:web.research"]
    sales = nodes["selection:research.discover_prospects:sales.research"]
    crm = nodes["selection:research.discover_prospects:crm.research"]

    assert web["normal_role"] == "primary"
    assert web["source_overrides"][0]["included"] is False
    assert sales["source_overrides"][0]["predicate_names"] == ["hubspot_source"]
    assert sales["source_overrides"][0]["role"] == "primary"
    assert crm["source_overrides"][0]["role"] == "fallback"
    assert crm["source_overrides"][0]["connection_hint"]["integration"] == "hubspot"


def test_inventory_preserves_resolver_readiness_surface() -> None:
    inventory = _inventory()
    nodes = {node["id"]: node for node in inventory["nodes"]}

    crm_upsert = nodes["selection:crm.pipeline_maintenance:gtm.crm_upsert"]
    assert crm_upsert["normal_role"] == "primary"
    assert crm_upsert["connection_hint"]["integration"] == "hubspot"
    assert crm_upsert["requires_instantiated_resolver_state"] is True
    assert set(crm_upsert["readiness_states"]) == {
        "catalog_only",
        "charter_blocked",
        "connection_required",
        "ready",
        "unavailable",
    }


def test_synthetic_resolver_only_action_is_reproducibly_detected(tmp_path: Path) -> None:
    catalog = tmp_path / MODULE.JOB_CATALOG_PATH
    resolver = tmp_path / MODULE.RESOLVER_PATH
    catalog.parent.mkdir(parents=True, exist_ok=True)
    resolver.parent.mkdir(parents=True, exist_ok=True)

    catalog.write_text(
        """
JOBS = (
    BusinessJob(
        job_key="synthetic.job",
        display_name="Synthetic job",
        vertical_role="vertical.test",
        candidate_actions=("synthetic.primary",),
        maturity="runtime_bound",
        credential_policy="none",
    ),
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    resolver.write_text(
        """
_ACTION_PREFERENCE = {"synthetic.job": ("synthetic.primary", "synthetic.rogue")}
_CONNECTION_HINTS = {}
_JOB_CONNECTION_HINTS = {}
_SOURCE_CONNECTION_HINTS = {}

def evaluate_action_candidate():
    return AbilitySelection(readiness="ready")

def resolve_jobs(jobs):
    return jobs
""".strip()
        + "\n",
        encoding="utf-8",
    )

    inventory = MODULE.collect_runtime_action_selection_inventory(tmp_path)
    findings = {finding["id"]: finding for finding in inventory["findings"]}
    assert "resolver-catalog-action-drift:synthetic.job:synthetic.rogue" in findings
    node = next(node for node in inventory["nodes"] if node["id"] == "selection:synthetic.job:synthetic.rogue")
    assert node["normal_role"] == "fallback"
    assert node["catalog_declared"] is False
