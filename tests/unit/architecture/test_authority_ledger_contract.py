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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ledger_blocks() -> list[str]:
    content = _read(LEDGER)
    return [block for block in content.split("\n  - id: ") if "authority_class:" in block]


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
