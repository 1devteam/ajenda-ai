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

INSERT_COLUMNS_RE = re.compile(
    r"INSERT\s+INTO\s+(?P<table>[a-z_]+)\s*\((?P<columns>.*?)\)",
    re.IGNORECASE | re.DOTALL,
)
INSERT_VALUES_TUPLE_RE = re.compile(r"\bVALUES\s*\((?P<values>.*?)\)\s*(?:ON\s+CONFLICT|$)", re.IGNORECASE | re.DOTALL)
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


def _split_sql_csv(raw: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    in_string = False
    depth = 0
    index = 0

    while index < len(raw):
        char = raw[index]

        if char == "'":
            current.append(char)
            if in_string and index + 1 < len(raw) and raw[index + 1] == "'":
                current.append(raw[index + 1])
                index += 1
            else:
                in_string = not in_string
        elif not in_string and char == "(":
            depth += 1
            current.append(char)
        elif not in_string and char == ")":
            depth = max(depth - 1, 0)
            current.append(char)
        elif not in_string and depth == 0 and char == ",":
            value = "".join(current).strip()
            if value:
                chunks.append(value)
            current = []
        else:
            current.append(char)

        index += 1

    tail = "".join(current).strip()
    if tail:
        chunks.append(tail)
    return chunks


def _iter_insert_values(migration_text: str) -> list[tuple[str, list[str], list[str]]]:
    results: list[tuple[str, list[str], list[str]]] = []
    for columns_match in INSERT_COLUMNS_RE.finditer(migration_text):
        table_name = columns_match.group("table").strip().lower()
        columns = [column.strip().lower() for column in _split_sql_csv(columns_match.group("columns"))]
        trailing_sql = migration_text[columns_match.end() :]
        values_match = INSERT_VALUES_TUPLE_RE.search(trailing_sql)
        if not values_match:
            continue
        values = _split_sql_csv(values_match.group("values"))
        if len(columns) != len(values):
            continue
        results.append((table_name, columns, values))
    return results


def _extract_json_literal(value_expression: str) -> str | None:
    match = JSONB_LITERAL_RE.search(value_expression)
    if match is None:
        return None
    return match.group("json").replace("''", "'")


def _check_migration(path: Path, migration_text: str) -> list[SeedShapeIssue]:
    issues: list[SeedShapeIssue] = []
    inserts = _iter_insert_values(migration_text)

    for table_name, columns, values in inserts:
        value_by_column = dict(zip(columns, values, strict=True))
        for field, expected_kind in FIELD_EXPECTED_JSON_KIND.items():
            expected_table, field_name = field.split(".", maxsplit=1)
            if table_name != expected_table or field_name not in value_by_column:
                continue

            literal = _extract_json_literal(value_by_column[field_name])
            if literal is None:
                continue

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
