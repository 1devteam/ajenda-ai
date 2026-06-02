"""Contract checks for Bundle 1.1 authority ledger governance."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER = REPO_ROOT / "docs" / "contracts" / "authority-ledger.v1.yaml"
README = REPO_ROOT / "README.md"

EXPECTED_AUTHORITY_CLASSES = {
    "declarative",
    "read_model",
    "governed_mutation",
    "runtime_authoritative",
}

RUNTIME_QUEUE_ADMISSION_ROUTE = "POST /v1/missions/{mission_id}/runtime-queue-admission"

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


def _block_for_route_scope(route_scope: str) -> str:
    matching_blocks = [block for block in _ledger_blocks() if f"- {route_scope}" in block]
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


def test_authority_ledger_only_uses_supported_authority_classes() -> None:
    content = _read(LEDGER)
    classes_in_ledger = {
        line.split(":", maxsplit=1)[1].strip()
        for line in content.splitlines()
        if line.strip().startswith("authority_class:")
    }
    assert classes_in_ledger
    assert classes_in_ledger.issubset(EXPECTED_AUTHORITY_CLASSES)


def test_runtime_queue_admission_route_is_first_class_runtime_authority() -> None:
    block = _block_for_route_scope(RUNTIME_QUEUE_ADMISSION_ROUTE)

    assert "authority_class: runtime_authoritative" in block
    assert "side_effect_class: tenant_scoped_queue_admission_mutation" in block
    assert "tests/contract/api/test_mission_queue_contract.py" in block


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
