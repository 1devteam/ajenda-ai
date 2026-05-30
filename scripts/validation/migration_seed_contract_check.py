"""Validate contract-sensitive JSONB seed literals in Alembic migrations.

This sentinel catches migration seed rows whose JSON literal shape disagrees with
API/domain contracts before those rows become tenant-visible data. It is
intentionally narrow and registry-driven: add table/field entries here when a
JSONB column has a stable public/domain contract that seed migrations must obey.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = REPO_ROOT / "alembic" / "versions"
IGNORE_MARKER = "migration-seed-contract: ignore"

JsonKind = Literal["array", "object"]

EXPECTED_JSON_KINDS: dict[str, dict[str, JsonKind]] = {
    "capabilities": {
        "supported_task_types": "array",
        "input_schema_hints": "object",
        "output_schema_hints": "object",
        "required_permissions": "array",
        "required_tools": "array",
        "approval_requirements": "object",
        "evidence_expectations": "array",
        "execution_constraints": "object",
    },
    "capability_adapters": {
        "supported_task_types": "array",
        "input_contract": "object",
        "output_contract": "object",
        "required_permissions": "array",
        "required_tools": "array",
        "approval_requirements": "object",
        "evidence_expectations": "array",
        "timeout_retry_hints": "object",
        "idempotency_expectations": "object",
    },
}

_INSERT_RE = re.compile(r"\bINSERT\s+INTO\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)\s*\(", re.IGNORECASE)
_JSONB_LITERAL_RE = re.compile(r"'((?:''|[^'])*)'\s*::\s*jsonb\b", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class SeedContractIssue:
    """A contract-sensitive seed literal mismatch."""

    path: Path
    line: int
    table: str
    field: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.table}.{self.field}: {self.message}"


@dataclass(frozen=True)
class InsertSeedStatement:
    """Parsed INSERT seed statement details needed for JSONB contract checks."""

    table: str
    columns: list[str]
    expressions: list[str]
    expression_offsets: list[int]


def _strip_identifier(identifier: str) -> str:
    return identifier.strip().strip('"').lower()


def _skip_whitespace(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _find_matching_paren(text: str, open_pos: int) -> int:
    depth = 0
    in_string = False
    pos = open_pos
    while pos < len(text):
        char = text[pos]
        if in_string:
            if char == "'":
                if pos + 1 < len(text) and text[pos + 1] == "'":
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == "'":
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos
        pos += 1
    raise ValueError("unclosed parenthesized SQL segment")


def _find_top_level_keyword(text: str, start: int, keyword: str) -> int:
    depth = 0
    in_string = False
    keyword_upper = keyword.upper()
    pos = start
    while pos < len(text):
        char = text[pos]
        if in_string:
            if char == "'":
                if pos + 1 < len(text) and text[pos + 1] == "'":
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == "'":
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        elif depth == 0 and text[pos : pos + len(keyword)].upper() == keyword_upper:
            before = text[pos - 1] if pos > 0 else " "
            after_pos = pos + len(keyword)
            after = text[after_pos] if after_pos < len(text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return pos
        pos += 1
    return -1


def _split_top_level_items(segment: str, base_offset: int) -> tuple[list[str], list[int]]:
    items: list[str] = []
    offsets: list[int] = []
    depth = 0
    in_string = False
    item_start = 0
    pos = 0
    while pos < len(segment):
        char = segment[pos]
        if in_string:
            if char == "'":
                if pos + 1 < len(segment) and segment[pos + 1] == "'":
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == "'":
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            raw = segment[item_start:pos]
            stripped = raw.strip()
            if stripped:
                leading = len(raw) - len(raw.lstrip())
                items.append(stripped)
                offsets.append(base_offset + item_start + leading)
            item_start = pos + 1
        pos += 1

    raw = segment[item_start:]
    stripped = raw.strip()
    if stripped:
        leading = len(raw) - len(raw.lstrip())
        items.append(stripped)
        offsets.append(base_offset + item_start + leading)
    return items, offsets


def _extract_insert_statements(text: str) -> list[InsertSeedStatement]:
    statements: list[InsertSeedStatement] = []
    for match in _INSERT_RE.finditer(text):
        table = _strip_identifier(match.group("table"))
        if table not in EXPECTED_JSON_KINDS:
            continue

        columns_open = match.end() - 1
        columns_close = _find_matching_paren(text, columns_open)
        column_items, _ = _split_top_level_items(text[columns_open + 1 : columns_close], columns_open + 1)
        columns = [_strip_identifier(item) for item in column_items]

        after_columns = _skip_whitespace(text, columns_close + 1)
        if text[after_columns : after_columns + len("VALUES")].upper() == "VALUES":
            values_pos = _skip_whitespace(text, after_columns + len("VALUES"))
            for expressions, offsets in _extract_values_rows(text, values_pos):
                statements.append(
                    InsertSeedStatement(
                        table=table,
                        columns=columns,
                        expressions=expressions,
                        expression_offsets=offsets,
                    )
                )
        elif text[after_columns : after_columns + len("SELECT")].upper() == "SELECT":
            select_start = after_columns + len("SELECT")
            from_pos = _find_top_level_keyword(text, select_start, "FROM")
            if from_pos == -1:
                continue
            expressions, offsets = _split_top_level_items(text[select_start:from_pos], select_start)
            statements.append(
                InsertSeedStatement(table=table, columns=columns, expressions=expressions, expression_offsets=offsets)
            )
        else:
            continue
    return statements


def _extract_values_rows(text: str, start: int) -> list[tuple[list[str], list[int]]]:
    rows: list[tuple[list[str], list[int]]] = []
    pos = start
    while pos < len(text):
        pos = _skip_whitespace(text, pos)
        if pos >= len(text) or text[pos] != "(":
            break

        values_close = _find_matching_paren(text, pos)
        rows.append(_split_top_level_items(text[pos + 1 : values_close], pos + 1))

        pos = _skip_whitespace(text, values_close + 1)
        if pos >= len(text) or text[pos] != ",":
            break
        pos = _skip_whitespace(text, pos + 1)
        if pos >= len(text) or text[pos] != "(":
            break
    return rows


def _json_kind(expression: str) -> JsonKind | None:
    match = _JSONB_LITERAL_RE.search(expression)
    if match is None:
        return None
    literal = match.group(1).replace("''", "'")
    value = json.loads(literal)
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return None


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def check_migration_file(path: Path) -> list[SeedContractIssue]:
    """Return seed contract issues for one Alembic migration file."""

    text = path.read_text(encoding="utf-8")
    if IGNORE_MARKER in text:
        return []

    issues: list[SeedContractIssue] = []
    for statement in _extract_insert_statements(text):
        expected_fields = EXPECTED_JSON_KINDS[statement.table]
        for index, field in enumerate(statement.columns):
            expected_kind = expected_fields.get(field)
            if expected_kind is None:
                continue
            if index >= len(statement.expressions):
                issues.append(
                    SeedContractIssue(
                        path=path,
                        line=_line_number(
                            text, statement.expression_offsets[-1] if statement.expression_offsets else 0
                        ),
                        table=statement.table,
                        field=field,
                        message="missing seed expression for contract-sensitive JSONB column",
                    )
                )
                continue
            expression = statement.expressions[index]
            line = _line_number(text, statement.expression_offsets[index])
            observed_kind = _json_kind(expression)
            if observed_kind is None:
                issues.append(
                    SeedContractIssue(
                        path=path,
                        line=line,
                        table=statement.table,
                        field=field,
                        message=(
                            f"expected {expected_kind} JSONB seed literal; add a literal that matches the "
                            f"API/domain contract or document an exception with {IGNORE_MARKER!r}"
                        ),
                    )
                )
            elif observed_kind != expected_kind:
                issues.append(
                    SeedContractIssue(
                        path=path,
                        line=line,
                        table=statement.table,
                        field=field,
                        message=f"expected {expected_kind} JSONB seed literal, found {observed_kind}",
                    )
                )
    return issues


def check_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[SeedContractIssue]:
    """Return all seed contract issues in Alembic migration files."""

    issues: list[SeedContractIssue] = []
    for path in sorted(migrations_dir.glob("*.py")):
        issues.extend(check_migration_file(path))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate JSONB seed literal shapes in Alembic migrations.")
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=MIGRATIONS_DIR,
        help="Directory containing Alembic migration files.",
    )
    args = parser.parse_args()

    issues = check_migrations(args.migrations_dir)
    for issue in issues:
        print(f"FAIL: {issue.render()}")

    if issues:
        return 1
    print("PASS: migration seed contract checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
