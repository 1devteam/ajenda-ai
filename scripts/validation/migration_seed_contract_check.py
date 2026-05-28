#!/usr/bin/env python3
"""Validate JSON seed literal shapes in Alembic migrations."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "alembic" / "versions"

FIELD_EXPECTED_JSON_KIND: dict[str, str] = {
    "capabilities.evidence_expectations": "array",
    "capability_adapters.evidence_expectations": "array",
}

INSERT_RE = re.compile(r"INSERT\s+INTO\s+(?P<table>[a-z_]+)\s*\((?P<columns>.*?)\)", re.IGNORECASE | re.DOTALL)
JSONB_LITERAL_RE = re.compile(r"'(?P<json>(?:[^']|'')*)'\s*::jsonb", re.IGNORECASE)


@dataclass
class SeedShapeIssue:
    migration_path: Path
    field_name: str
    expected_kind: str
    observed_kind: str


def _load_migration_texts() -> list[tuple[Path, str]]:
    return sorted(
        ((path, path.read_text(encoding="utf-8")) for path in MIGRATIONS_DIR.glob("*.py")), key=lambda x: x[0].name
    )


def _json_kind(value: object) -> str:
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "scalar"


def _table_has_column(migration_text: str, table_name: str, column_name: str) -> bool:
    for match in INSERT_RE.finditer(migration_text):
        if match.group("table").strip().lower() != table_name:
            continue
        columns = {column.strip().lower() for column in match.group("columns").split(",") if column.strip()}
        if column_name in columns:
            return True
    return False


def _field_context_literals(migration_text: str, field_name: str) -> list[str]:
    literals: list[str] = []
    lines = migration_text.splitlines()
    for index, line in enumerate(lines):
        if field_name not in line:
            continue
        window = "\n".join(lines[index : index + 8])
        match = JSONB_LITERAL_RE.search(window)
        if match:
            literals.append(match.group("json").replace("''", "'"))
    return literals


def _check_migration(path: Path, migration_text: str) -> list[SeedShapeIssue]:
    issues: list[SeedShapeIssue] = []

    for field, expected_kind in FIELD_EXPECTED_JSON_KIND.items():
        table_name, field_name = field.split(".", maxsplit=1)
        if not _table_has_column(migration_text, table_name, field_name):
            continue

        for literal in _field_context_literals(migration_text, field_name):
            try:
                decoded = json.loads(literal)
            except json.JSONDecodeError:
                continue
            observed_kind = _json_kind(decoded)
            if observed_kind != expected_kind:
                issues.append(
                    SeedShapeIssue(
                        migration_path=path,
                        field_name=field,
                        expected_kind=expected_kind,
                        observed_kind=observed_kind,
                    )
                )
    return issues


def main() -> int:
    issues: list[SeedShapeIssue] = []
    for path, text in _load_migration_texts():
        issues.extend(_check_migration(path, text))

    if not issues:
        print("PASS: migration seed contract parity checks passed.")
        return 0

    for issue in issues:
        rel_path = issue.migration_path.relative_to(REPO_ROOT)
        print(f"FAIL: {rel_path} seeds {issue.field_name} as {issue.observed_kind}; expected {issue.expected_kind}.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
