"""Contract checks for Bundle 1.1 authority ledger governance."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER = REPO_ROOT / "docs" / "contracts" / "authority-ledger.v1.yaml"
README = REPO_ROOT / "README.md"

EXPECTED_AUTHORITY_CLASSES = {
    "declarative",
    "read_model",
    "governed_mutation",
    "runtime_authoritative",
}

POST_V1_MISSIONS_MISSION_ID_RUNTIME_QUEUE_ADMISSION_ROUTE = "POST /v1/missions/{mission_id}/runtime-queue-admission"
POST_V1_MISSIONS_MISSION_ID_QUEUE_ROUTE = "POST /v1/missions/{mission_id}/queue"

MIXED_METHOD_ADMISSION_PATHS = {
    "/v1/missions/{mission_id}/runtime-task-materialization": {
        "GET": "read_model",
        "POST": "governed_mutation",
    },
    "/v1/missions/{mission_id}/worker-claim-admission": {
        "GET": "read_model",
        "POST": "governed_mutation",
    },
    "/v1/missions/{mission_id}/worker-start-admission": {
        "GET": "read_model",
        "POST": "governed_mutation",
    },
    "/v1/missions/{mission_id}/worker-run-admission": {
        "GET": "read_model",
        "POST": "runtime_authoritative",
    },
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ledger_blocks() -> list[str]:
    content = _read(LEDGER)
    # Split on top-level authority entry marker and keep every declared entry.
    # Do not pre-filter by any required field (such as authority_class), or
    # malformed entries could evade required-field validation.
    parts = content.split("\n  - id: ")
    return [f"id: {block}" for block in parts[1:] if block.strip()]


def _route_scope_items(block: str) -> list[str]:
    items: list[str] = []
    in_route_scope = False
    for line in block.splitlines():
        if line.startswith("    route_scope:"):
            in_route_scope = True
            continue
        if in_route_scope and line.startswith("    ") and not line.startswith("      "):
            break
        if in_route_scope and line.startswith("      - "):
            items.append(line.removeprefix("      - ").strip())
    return items


def _block_for_route_scope(route_scope: str) -> str:
    matching_blocks = [block for block in _ledger_blocks() if route_scope in _route_scope_items(block)]
    assert len(matching_blocks) == 1, f"Expected exactly one ledger entry for route scope: {route_scope}"
    return matching_blocks[0]


def test_authority_ledger_is_present_and_referenced_in_readme() -> None:
    assert LEDGER.exists()
    readme = _read(README)
    assert "docs/contracts/authority-ledger.v1.yaml" in readme


def test_authority_ledger_entries_include_required_contract_fields() -> None:
    blocks = _ledger_blocks()
    assert blocks, "Expected at least one authority ledger entry."

    required_keys = (
        "area:",
        "source_of_truth:",
        "route_scope:",
        "authority_class:",
        "side_effect_class:",
        "allowed_side_effects:",
        "forbidden_side_effects:",
        "required_proofs:",
    )

    for block in blocks:
        for key in required_keys:
            assert key in block


def test_decision_episode_materialization_has_one_declared_owner() -> None:
    blocks = [block for block in _ledger_blocks() if block.startswith("id: decision_episode_materialization\n")]
    assert len(blocks) == 1
    block = blocks[0]
    assert "backend/services/decision_episode_materialization.py" in block
    assert "sole owner of durable decision-to-learning episode reconstruction" in block
    assert "caller-authored decision identity" in block


def test_route_scope_item_parser_finds_second_or_later_route_scope_items() -> None:
    block = """id: example_contract
    area: example
    route_scope:
      - GET /v1/example
      - POST /v1/example
    authority_class: read_model
"""

    assert _route_scope_items(block) == ["GET /v1/example", "POST /v1/example"]


def test_block_for_route_scope_rejects_duplicate_second_or_later_route_scope_items() -> None:
    first_block = """id: first_contract
    area: first
    route_scope:
      - POST /v1/example
    authority_class: read_model
"""
    second_block = """id: second_contract
    area: second
    route_scope:
      - GET /v1/other
      - POST /v1/example
    authority_class: read_model
"""

    with patch(__name__ + "._ledger_blocks", return_value=[first_block, second_block]):
        try:
            _block_for_route_scope("POST /v1/example")
        except AssertionError as exc:
            assert "Expected exactly one ledger entry" in str(exc)
        else:
            raise AssertionError("Expected duplicate route_scope detection to fail")


def test_authority_ledger_only_uses_supported_authority_classes() -> None:
    content = _read(LEDGER)
    classes_in_ledger = {
        line.split(":", maxsplit=1)[1].strip()
        for line in content.splitlines()
        if line.strip().startswith("authority_class:")
    }
    assert classes_in_ledger
    assert classes_in_ledger.issubset(EXPECTED_AUTHORITY_CLASSES)


def test_post_v1_missions_mission_id_runtime_queue_admission_route_is_first_class_runtime_authority() -> None:
    block = _block_for_route_scope(POST_V1_MISSIONS_MISSION_ID_RUNTIME_QUEUE_ADMISSION_ROUTE)

    assert "authority_class: runtime_authoritative" in block
    assert "side_effect_class: tenant_scoped_queue_admission_mutation" in block
    assert "tests/contract/api/test_mission_queue_contract.py" in block


def test_post_v1_missions_mission_id_queue_route_has_dedicated_authority_coverage() -> None:
    block = _block_for_route_scope(POST_V1_MISSIONS_MISSION_ID_QUEUE_ROUTE)
    runtime_block = _block_for_route_scope(POST_V1_MISSIONS_MISSION_ID_RUNTIME_QUEUE_ADMISSION_ROUTE)

    assert "id: post_v1_missions_mission_id_queue_compatibility_wrapper_contract" in block
    assert "side_effect_class: tenant_scoped_queue_admission_compatibility_wrapper" in block
    assert "enforcement_role: api_adapter_only" in block
    assert "API compatibility wrapper" in block
    assert "MissionRuntimeQueueAdmissionService.admit()" in block
    assert "sole runtime enforcement authority" in block
    assert "route itself is only an authenticated API adapter" in block
    assert "call MissionExecutor.queue_all_planned_tasks()" in block
    assert "ExecutionCoordinator.queue_task()" in block
    assert "persists the same runtime_queue_admission metadata" in block
    assert "direct QueueAdapter enqueue" in block
    assert "TaskDispatcher" in block
    assert "worker leases" in block
    assert "tests/contract/api/test_mission_queue_contract.py" in block

    assert block != runtime_block
    assert "tenant_scoped_queue_admission_mutation" in runtime_block
    assert "enforcement_role: canonical_api_adapter_to_service_authority" in runtime_block
    assert "sole runtime admission authority" in runtime_block
    assert "persists runtime_queue_admission metadata, receipts, blockers" in runtime_block
    assert "MissionExecutor.queue_all_planned_tasks()" not in runtime_block


def test_mixed_method_admission_routes_are_method_specific() -> None:
    content = _read(LEDGER)

    for path, methods in MIXED_METHOD_ADMISSION_PATHS.items():
        assert f"- {path}" not in content, f"Ledger must classify mixed-method route by HTTP method: {path}"
        for method in methods:
            assert f"- {method} {path}" in content


def test_mixed_method_admission_routes_use_expected_authority_classes() -> None:
    for path, methods in MIXED_METHOD_ADMISSION_PATHS.items():
        for method, expected_authority_class in methods.items():
            block = _block_for_route_scope(f"{method} {path}")
            assert f"authority_class: {expected_authority_class}" in block


def test_tool_action_providers_do_not_import_worker_runtime_completion_authority() -> None:
    import ast

    provider_paths = [
        path
        for path in (REPO_ROOT / "backend" / "services" / "tools").glob("*_actions.py")
        if path.name not in {"runtime_authority.py"}
    ]
    assert provider_paths
    for path in provider_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "backend.services.worker_runtime_service", path
            elif isinstance(node, ast.Import):
                assert all(alias.name != "backend.services.worker_runtime_service" for alias in node.names), path
