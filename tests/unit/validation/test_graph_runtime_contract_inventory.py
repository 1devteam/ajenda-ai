from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts/validation/graph_runtime_contract_inventory.py"
SPEC = importlib.util.spec_from_file_location("ajenda_graph_runtime_contract_inventory", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _inventory():
    return MODULE.collect_runtime_contract_inventory(REPO_ROOT)


def test_inventory_exposes_jobs_artifacts_inputs_and_actions() -> None:
    inventory = _inventory()
    nodes = {node["id"]: node for node in inventory["nodes"]}

    assert nodes["job:intelligence.retrieve_knowledge"]["type"] == "business_job"
    assert nodes["artifact:observed_contacts"]["type"] == "runtime_artifact"
    assert nodes["artifact:retrieved_knowledge"]["type"] == "runtime_artifact"
    assert nodes["action:knowledge.retrieve_current"]["type"] == "runtime_action"
    assert nodes["input:target_industry_or_query"]["type"] == "runtime_input"


def test_inventory_preserves_dependency_kinds_and_conditions() -> None:
    inventory = _inventory()
    edges = inventory["edges"]

    hard = next(
        edge
        for edge in edges
        if edge["from"] == "job:intelligence.retrieve_knowledge" and edge["to"] == "job:research.observe_sources"
    )
    optional = next(
        edge
        for edge in edges
        if edge["from"] == "job:intelligence.advise_next" and edge["to"] == "job:intelligence.retrieve_knowledge"
    )
    conditional = next(
        edge
        for edge in edges
        if edge["from"] == "job:research.observe_sources" and edge["to"] == "job:research.discover_prospects"
    )

    assert hard["type"] == "depends_on_hard"
    assert optional["type"] == "depends_on_optional"
    assert conditional["type"] == "depends_on_conditional"
    assert conditional["required_when_missing"] == ["prospect_candidates"]
    assert conditional["satisfied_by"] == ["explicit_company", "crm_record", "prior_artifact"]


def test_artifact_flow_uses_consumer_to_dependency_direction() -> None:
    inventory = _inventory()
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in inventory["edges"]}

    assert (
        "job:intelligence.retrieve_knowledge",
        "artifact:observed_contacts",
        "requires_artifact",
    ) in edges
    assert (
        "artifact:observed_contacts",
        "job:research.observe_sources",
        "produced_by",
    ) in edges


def test_action_nodes_link_to_discoverable_handler_modules() -> None:
    inventory = _inventory()
    nodes = {node["id"]: node for node in inventory["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in inventory["edges"]}

    action = nodes["action:knowledge.retrieve_current"]
    assert "backend/services/tools/knowledge_actions.py" in action["implementation_sources"]
    assert (
        "action:knowledge.retrieve_current",
        "py:backend.services.tools.knowledge_actions",
        "implemented_in",
    ) in edges


def test_current_catalog_has_no_runtime_contract_inventory_violations() -> None:
    inventory = _inventory()

    assert inventory["findings"] == []
    assert inventory["metrics"]["job_count"] > 0
    assert inventory["metrics"]["artifact_count"] > 0
    assert inventory["metrics"]["typed_dependency_count"] > 0
