import pytest

from scripts.validation.migration_semantic_probe import _ensure_list_of_strings


def test_ensure_list_of_strings_accepts_string_lists() -> None:
    _ensure_list_of_strings(["approval_decision", "send_outcome"], field_name="x")


def test_ensure_list_of_strings_rejects_non_list() -> None:
    with pytest.raises(AssertionError, match="must be a JSON array"):
        _ensure_list_of_strings({"required_events": ["approval_decision"]}, field_name="x")


def test_ensure_list_of_strings_rejects_non_string_entries() -> None:
    with pytest.raises(AssertionError, match="entries must all be strings"):
        _ensure_list_of_strings(["approval_decision", 1], field_name="x")
