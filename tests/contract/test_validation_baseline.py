from pathlib import Path

AUTHORITATIVE_COMMANDS = (
    "ruff check backend/ tests/",
    "ruff format --check backend/ tests/",
    "pytest -q tests/unit/ tests/contract/",
    "pytest -q",
)


def test_validation_baseline_lists_authoritative_commands() -> None:
    text = Path("docs/validation/rebuild-validation-baseline.md").read_text()

    for command in AUTHORITATIVE_COMMANDS:
        assert command in text


def test_readme_points_to_validation_baseline() -> None:
    readme = Path("README.md").read_text()

    assert "docs/validation/rebuild-validation-baseline.md" in readme
