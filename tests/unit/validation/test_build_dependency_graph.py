from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[3] / "scripts/validation/build_dependency_graph.py"
SPEC = importlib.util.spec_from_file_location("ajenda_build_dependency_graph", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_graph_contains_static_semantic_and_test_layers() -> None:
    graph = MODULE.build_graph()

    node_ids = {node["id"] for node in graph["nodes"]}
    edge_types = {edge["type"] for edge in graph["edges"]}
    invariant_ids = {item["id"] for item in graph["invariants"]}

    assert "py:backend.main" in node_ids
    assert "py:services.hubspot_crm_adapter.main" in node_ids
    assert "boundary:tenant-db" in node_ids
    assert "py:backend.services.execution_coordinator" in node_ids
    assert any(node_id.startswith("test:tests/") for node_id in node_ids)
    assert "imports" in edge_types
    assert "tests" in edge_types
    assert "http_contract" in edge_types
    assert "tenant-isolation" in invariant_ids
    assert "runtime-secret-boundary" in invariant_ids


def test_graph_maps_frontier_template_as_governance_input() -> None:
    graph = MODULE.build_graph()
    node_ids = {node["id"] for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    assert "contract:graft-plus-frontier-spec-v2" in node_ids
    assert (
        "graph-tool:scripts.validation.graft_plus_frontier",
        "contract:graft-plus-frontier-spec-v2",
        "consumes_governance_contract",
    ) in edges


def test_graph_maps_its_overlay_as_builder_input() -> None:
    graph = MODULE.build_graph()
    node_ids = {node["id"] for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    assert "contract:dependency-graph-overlay-v1" in node_ids
    assert (
        "graph-tool:scripts.validation.build_dependency_graph",
        "contract:dependency-graph-overlay-v1",
        "consumes_governance_contract",
    ) in edges


def test_graph_contains_browser_deployment_support_edges() -> None:
    graph = MODULE.build_graph()
    node_ids = {node["id"] for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    assert {"dependency:playwright", "runtime-binary:chromium", "deployment-browser:worker-image"} <= node_ids
    assert (
        "action:web.browser_session",
        "dependency:playwright",
        "requires_runtime_dependency",
    ) in edges
    assert (
        "runtime-binary:chromium",
        "deployment-browser:worker-image",
        "installed_in",
    ) in edges
    assert graph["deployment_runtime_metrics"]["deployment_unknown_count"] == 1
    assert graph["deployment_runtime_unknowns"][0]["id"] == "deployment-browser:flag-value-externalized"


def test_mission_composition_has_selective_function_layer() -> None:
    graph = MODULE.build_graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    segment = "fn:backend.services.mission_composition.intent_interpreter:_segment_clauses"
    classify = "fn:backend.services.mission_composition.intent_interpreter:_classify_clause"
    interpret = "fn:backend.services.mission_composition.intent_interpreter:interpret_instruction"
    normalize = "fn:backend.services.mission_composition.interpretation.normalize:normalize_instruction_text"

    assert nodes[segment]["type"] == "python_function"
    assert nodes[segment]["decision_role"] == "segments_text"
    assert nodes[classify]["decision_role"] == "classifies_materiality"
    assert nodes[interpret]["decision_role"] == "interprets_mission"
    assert nodes[normalize]["decision_role"] == "normalizes_text"
    assert (
        segment,
        "py:backend.services.mission_composition.intent_interpreter",
        "defined_in",
    ) in edges
    assert any(edge[0] == interpret and edge[1] == segment and edge[2] == "calls_function" for edge in edges)
    assert any(edge[0] == interpret and edge[1] == classify and edge[2] == "calls_function" for edge in edges)


def test_direct_function_test_edges_are_supplemental() -> None:
    graph = MODULE.build_graph()
    edges = graph["edges"]

    assert any(
        edge["type"] == "tests_function" and str(edge["to"]).startswith("fn:backend.services.mission_composition.")
        for edge in edges
    )
    assert any(edge["type"] == "tests" for edge in edges)


def test_runtime_route_and_action_surfaces_have_symbol_resolution() -> None:
    graph = MODULE.build_graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    worker_claim = "fn:backend.services.worker_runtime_service:WorkerRuntimeService.claim_next_task"
    mission_compile = "fn:backend.api.routes.mission:compile_mission"
    mission_route = "route:backend.api.routes.mission:POST:/missions/{mission_id}/compile"
    ability_launch = "fn:backend.api.routes.ability_runtime:launch_task"
    ability_route = "route:backend.api.routes.ability_runtime:POST:/ability-runtime/tasks"
    web_handler = "fn:backend.services.tools.web_action_io:web_page_read"
    social_handler = "fn:backend.services.tools.gtm_action_social:social_publish_handler"

    assert nodes[worker_claim]["type"] == "python_method"
    assert nodes[worker_claim]["owner_class"] == "WorkerRuntimeService"
    assert nodes[mission_route]["type"] == "http_route"
    assert nodes[mission_route]["method"] == "POST"
    assert nodes[ability_route]["path"] == "/ability-runtime/tasks"
    assert (mission_route, mission_compile, "handled_by") in edges
    assert (ability_route, ability_launch, "handled_by") in edges
    assert ("action:web.page_read", web_handler, "implemented_by") in edges
    assert ("action:gtm.social_publish", social_handler, "implemented_by") in edges


def test_selected_worker_methods_receive_direct_test_edges() -> None:
    graph = MODULE.build_graph()
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    test_node = "test:tests/unit/services/test_worker_runtime_service_transaction_contract.py"
    complete = "fn:backend.services.worker_runtime_service:WorkerRuntimeService.complete"

    assert (test_node, complete, "tests_function") in edges


def test_package_relative_re_exports_are_graph_edges() -> None:
    graph = MODULE.build_graph()
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    assert ("py:backend.workers", "py:backend.workers.worker_loop", "imports") in edges


def test_standalone_service_imports_are_graph_edges() -> None:
    graph = MODULE.build_graph()
    edges = {(edge["from"], edge["to"], edge["type"]) for edge in graph["edges"]}

    assert (
        "py:services.hubspot_crm_adapter.main",
        "py:services.hubspot_crm_adapter.hubspot",
        "imports",
    ) in edges
    assert (
        "py:services.hubspot_crm_adapter.main",
        "py:services.hubspot_crm_adapter.models",
        "imports",
    ) in edges


def test_test_impact_edges_target_production_modules() -> None:
    graph = MODULE.build_graph()
    test_edges = [edge for edge in graph["edges"] if edge["type"] == "tests"]

    assert test_edges
    assert all(edge["from"].startswith("test:tests/") for edge in test_edges)
    assert all(edge["to"].startswith(("py:backend.", "py:services.")) for edge in test_edges)


def test_every_edge_endpoint_is_defined() -> None:
    graph = MODULE.build_graph()
    node_ids = {node["id"] for node in graph["nodes"]}

    for edge in graph["edges"]:
        assert edge["from"] in node_ids
        assert edge["to"] in node_ids


def test_metrics_cover_graph() -> None:
    graph = MODULE.build_graph()

    assert graph["metrics"]["node_count"] == len(graph["nodes"])
    assert graph["metrics"]["edge_count"] == len(graph["edges"])
    assert graph["metrics"]["edge_counts_by_type"]["tests"] > 0
    assert graph["metrics"]["edge_counts_by_type"]["calls_function"] > 0
    assert graph["metrics"]["edge_counts_by_type"]["tests_function"] > 0
    assert isinstance(graph["metrics"]["static_cycles"], list)
    assert graph["metrics"]["top_fan_in"]
    assert graph["metrics"]["top_production_fan_in"]
    assert graph["metrics"]["top_fan_out"]


def test_invariant_statuses_are_explicit() -> None:
    graph = MODULE.build_graph()
    allowed = {
        "enforced",
        "enforced_doctrine",
        "enforced_design_boundary",
        "enforced_meta_invariant",
        "policy_drift",
        "known_violation",
    }

    assert graph["invariants"]
    for invariant in graph["invariants"]:
        assert invariant["status"] in allowed
        assert invariant["rule"].strip()
        assert invariant["sources"]


def test_display_path_accepts_repository_and_external_outputs(tmp_path: Path) -> None:
    repository_output = MODULE.REPO_ROOT / "artifacts" / "graph.json"
    external_output = tmp_path / "graph.json"

    assert MODULE._display_path(repository_output) == "artifacts/graph.json"
    assert MODULE._display_path(external_output) == str(external_output.resolve())
