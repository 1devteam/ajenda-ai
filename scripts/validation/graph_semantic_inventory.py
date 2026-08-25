#!/usr/bin/env python3
"""Derive semantic architecture facts that imports cannot express.

The canonical graph uses this inventory for two source-backed domains:
- Alembic table/RLS state, including tenant-isolation coverage.
- Production HTTP/SMTP egress sinks and their reviewed classifications.

Known baseline defects remain findings; acknowledgements only ratchet the detector
and never constitute remediation evidence.
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_RLS_ENABLE_RE = re.compile(r"ALTER\s+TABLE\s+([A-Za-z0-9_]+)\s+ENABLE\s+ROW\s+LEVEL\s+SECURITY", re.I)
_RLS_FORCE_RE = re.compile(r"ALTER\s+TABLE\s+([A-Za-z0-9_]+)\s+FORCE\s+ROW\s+LEVEL\s+SECURITY", re.I)
_POLICY_RE = re.compile(r"CREATE\s+POLICY\s+([A-Za-z0-9_]+)\s+ON\s+([A-Za-z0-9_]+)", re.I)
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "request", "head", "options"})
_NETWORK_LIBRARIES = frozenset({"httpx", "requests", "smtplib"})


def _module_for_path(repo_root: Path, path: Path) -> str:
    rel = path.relative_to(repo_root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_string_sequence(node: ast.AST | None) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return None
    values = tuple(value for item in node.elts if (value := _literal_string(item)) is not None)
    return values if values and len(values) == len(node.elts) else None


def _named_string_sequences(tree: ast.Module) -> dict[str, tuple[str, ...]]:
    """Collect statically literal string collections used by migration loops."""
    result: dict[str, tuple[str, ...]] = {}
    for statement in ast.walk(tree):
        target: ast.AST | None = None
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign):
            target, value = statement.target, statement.value
        if not isinstance(target, ast.Name):
            continue
        items = _literal_string_sequence(value)
        if items:
            result[target.id] = items
    return result


def _joined_string_template(node: ast.JoinedStr) -> str:
    parts: list[str] = []
    for item in node.values:
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            parts.append(item.value)
        elif isinstance(item, ast.FormattedValue):
            if isinstance(item.value, ast.Name):
                parts.append("{" + item.value.id + "}")
            else:
                parts.append("{expr}")
    return "".join(parts)


def _rendered_strings(node: ast.AST) -> list[str]:
    strings: list[str] = []
    for item in ast.walk(node):
        if isinstance(item, ast.Constant) and isinstance(item.value, str):
            strings.append(item.value)
        elif isinstance(item, ast.JoinedStr):
            strings.append(_joined_string_template(item))
    return strings


def _record_rls_sql(
    sql: str,
    *,
    enabled: set[str],
    forced: set[str],
    policies: dict[str, set[str]],
) -> None:
    enabled.update(match.group(1) for match in _RLS_ENABLE_RE.finditer(sql))
    forced.update(match.group(1) for match in _RLS_FORCE_RE.finditer(sql))
    for match in _POLICY_RE.finditer(sql):
        policies[match.group(2)].add(match.group(1))


def _loop_values(loop: ast.For, named_sequences: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    if isinstance(loop.iter, ast.Name):
        return named_sequences.get(loop.iter.id)
    return _literal_string_sequence(loop.iter)


def _record_loop_rls(
    tree: ast.Module,
    named_sequences: dict[str, tuple[str, ...]],
    *,
    enabled: set[str],
    forced: set[str],
    policies: dict[str, set[str]],
) -> None:
    """Resolve RLS SQL emitted from loops over literal/named table collections."""
    for loop in (item for item in ast.walk(tree) if isinstance(item, ast.For)):
        if not isinstance(loop.target, ast.Name):
            continue
        tables = _loop_values(loop, named_sequences)
        if not tables:
            continue
        marker = "{" + loop.target.id + "}"
        for template in _rendered_strings(loop):
            if marker not in template:
                continue
            for table in tables:
                _record_rls_sql(
                    template.replace(marker, table),
                    enabled=enabled,
                    forced=forced,
                    policies=policies,
                )


def _migration_table_changes(tree: ast.Module) -> dict[str, set[str]]:
    """Return table -> columns created/added by one migration."""
    tables: dict[str, set[str]] = defaultdict(set)
    for item in ast.walk(tree):
        if not isinstance(item, ast.Call):
            continue
        call_name = _call_name(item.func)
        if call_name == "op.create_table" and item.args:
            table = _literal_string(item.args[0])
            if not table:
                continue
            tables.setdefault(table, set())
            for argument in item.args[1:]:
                if not isinstance(argument, ast.Call):
                    continue
                if _call_name(argument.func) not in {"sa.Column", "sqlalchemy.Column"} or not argument.args:
                    continue
                column = _literal_string(argument.args[0])
                if column:
                    tables[table].add(column)
        elif call_name == "op.add_column" and len(item.args) >= 2:
            table = _literal_string(item.args[0])
            column_call = item.args[1]
            if not table or not isinstance(column_call, ast.Call):
                continue
            if _call_name(column_call.func) not in {"sa.Column", "sqlalchemy.Column"} or not column_call.args:
                continue
            column = _literal_string(column_call.args[0])
            if column:
                tables[table].add(column)
    return dict(tables)


def _migration_inventory(repo_root: Path) -> dict[str, Any]:
    root = repo_root / "alembic" / "versions"
    touched_by: dict[str, set[str]] = defaultdict(set)
    columns: dict[str, set[str]] = defaultdict(set)
    enabled: set[str] = set()
    forced: set[str] = set()
    policies: dict[str, set[str]] = defaultdict(set)
    migrations: list[dict[str, Any]] = []

    for path in sorted(root.glob("*.py")):
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError:
            continue

        table_changes = _migration_table_changes(tree)
        migration_enabled: set[str] = set()
        migration_forced: set[str] = set()
        migration_policies: dict[str, set[str]] = defaultdict(set)
        _record_rls_sql(
            text,
            enabled=migration_enabled,
            forced=migration_forced,
            policies=migration_policies,
        )
        _record_loop_rls(
            tree,
            _named_string_sequences(tree),
            enabled=migration_enabled,
            forced=migration_forced,
            policies=migration_policies,
        )

        enabled.update(migration_enabled)
        forced.update(migration_forced)
        for table, policy_names in migration_policies.items():
            policies[table].update(policy_names)

        rls_tables = migration_enabled | migration_forced | set(migration_policies)
        migration_tables = set(table_changes) | rls_tables
        migrations.append({"source": rel, "tables": sorted(migration_tables)})
        for table in migration_tables:
            touched_by[table].add(rel)
        for table, table_columns in table_changes.items():
            columns[table].update(table_columns)

    return {
        "migrations": migrations,
        "touched_by": touched_by,
        "columns": columns,
        "enabled": enabled,
        "forced": forced,
        "policies": policies,
    }


def _rls_semantics(
    repo_root: Path,
    overlay: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    inventory = _migration_inventory(repo_root)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    exemptions = {
        str(item["table"]): str(item["reason"])
        for item in overlay.get("rls_exempt_tables", [])
        if item.get("table") and item.get("reason")
    }
    nonblocking = {
        str(item["table"]): str(item["reason"])
        for item in overlay.get("rls_nonblocking_tables", [])
        if item.get("table") and item.get("reason")
    }

    for migration in inventory["migrations"]:
        source = str(migration["source"])
        migration_id = f"migration:{Path(source).stem}"
        nodes.append({"id": migration_id, "type": "migration", "source": source})
        for table in migration["tables"]:
            edges.append(
                {
                    "from": migration_id,
                    "to": f"db:table:{table}",
                    "type": "creates_or_alters_table",
                    "evidence": source,
                }
            )

    for table in sorted(inventory["columns"]):
        sources = sorted(inventory["touched_by"].get(table, set()))
        source = sources[-1] if sources else None
        tenant_associated = "tenant_id" in inventory["columns"][table]
        policy_names = sorted(inventory["policies"].get(table, set()))
        tenant_policies = [name for name in policy_names if name != "admin_bypass"]
        rls_enabled = table in inventory["enabled"]
        rls_forced = table in inventory["forced"]
        has_admin_bypass = "admin_bypass" in policy_names
        rls_complete = bool(rls_enabled and rls_forced and tenant_policies and has_admin_bypass)
        exempt_reason = exemptions.get(table)

        node: dict[str, Any] = {
            "id": f"db:table:{table}",
            "type": "database_table",
            "label": table,
            "tenant_associated": tenant_associated,
            "rls_enabled": rls_enabled,
            "rls_forced": rls_forced,
            "rls_policies": policy_names,
            "rls_complete": rls_complete,
            "rls_exempt": exempt_reason is not None,
        }
        if source:
            node["source"] = source
        if exempt_reason:
            node["rls_exempt_reason"] = exempt_reason
        nodes.append(node)

        evidence = source or "alembic/versions"
        edges.append(
            {"from": f"db:table:{table}", "to": "external:postgresql", "type": "stored_in", "evidence": evidence}
        )
        if tenant_associated:
            edges.append(
                {
                    "from": f"db:table:{table}",
                    "to": "boundary:tenant-db",
                    "type": "tenant_data_boundary",
                    "evidence": evidence,
                }
            )
        if tenant_associated and rls_complete:
            edges.append(
                {
                    "from": f"db:table:{table}",
                    "to": "boundary:tenant-db",
                    "type": "rls_enforced",
                    "evidence": evidence,
                }
            )

        if not tenant_associated or rls_complete or exempt_reason:
            continue

        missing: list[str] = []
        if not rls_enabled:
            missing.append("ENABLE ROW LEVEL SECURITY")
        if not rls_forced:
            missing.append("FORCE ROW LEVEL SECURITY")
        if not tenant_policies:
            missing.append("tenant isolation policy")
        if not has_admin_bypass:
            missing.append("admin_bypass policy")
        findings.append(
            {
                "id": f"rls-missing:{table}",
                "category": "database-isolation",
                "severity": "high",
                "summary": f"Tenant-associated table {table} lacks complete RLS enforcement",
                "details": {"missing": missing},
                "evidence": sources,
                "related_nodes": [f"db:table:{table}", "boundary:tenant-db"],
                "blocking": table not in nonblocking,
                "classification": "known_gap" if table in nonblocking else "violation",
                "reason": nonblocking.get(table),
            }
        )

    return nodes, edges, findings


def _network_import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for item in tree.body:
        if isinstance(item, ast.Import):
            for alias in item.names:
                root = alias.name.split(".", 1)[0]
                if root in _NETWORK_LIBRARIES:
                    aliases[alias.asname or root] = root
        elif isinstance(item, ast.ImportFrom) and item.module:
            root = item.module.split(".", 1)[0]
            if root in _NETWORK_LIBRARIES:
                for alias in item.names:
                    aliases[alias.asname or alias.name] = f"{root}.{alias.name}"
    return aliases


def _network_calls(tree: ast.Module) -> list[dict[str, Any]]:
    aliases = _network_import_aliases(tree)
    if not aliases:
        return []

    client_vars: set[str] = set()
    calls: list[dict[str, Any]] = []
    for item in ast.walk(tree):
        if not isinstance(item, (ast.Assign, ast.AnnAssign)):
            continue
        value = item.value
        if not isinstance(value, ast.Call):
            continue
        name = _call_name(value.func) or ""
        root_alias = name.split(".", 1)[0]
        resolved = name.replace(root_alias, aliases.get(root_alias, root_alias), 1)
        if not resolved.startswith(("httpx.Client", "httpx.AsyncClient", "requests.Session", "smtplib.SMTP")):
            continue
        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
        client_vars.update(target.id for target in targets if isinstance(target, ast.Name))

    for item in ast.walk(tree):
        if not isinstance(item, ast.Call):
            continue
        name = _call_name(item.func) or ""
        parts = name.split(".")
        root = parts[0] if parts else ""
        resolved_root = aliases.get(root, root)
        kind: str | None = None

        if resolved_root in {"httpx", "requests"} and len(parts) >= 2 and parts[-1].lower() in _HTTP_METHODS:
            kind = f"{resolved_root}.{parts[-1].lower()}"
        elif root in client_vars and len(parts) >= 2 and parts[-1].lower() in _HTTP_METHODS:
            kind = f"client.{parts[-1].lower()}"
        elif resolved_root == "smtplib" and len(parts) >= 2 and parts[-1] in {"SMTP", "SMTP_SSL"}:
            kind = f"smtplib.{parts[-1]}"
        else:
            resolved_name = name.replace(root, resolved_root, 1)
            if resolved_name in {"httpx.Client", "httpx.AsyncClient", "requests.Session"}:
                kind = resolved_name + ".construct"
        if kind is None:
            continue

        literal_urls: list[str] = []
        arguments = [*item.args, *(keyword.value for keyword in item.keywords)]
        for argument in arguments:
            for descendant in ast.walk(argument):
                value = _literal_string(descendant)
                if value and value.startswith(("https://", "http://")):
                    literal_urls.append(value)
        hosts = sorted(
            {hostname for url in literal_urls if (hostname := (urlparse(url).hostname or "").lower().strip())}
        )
        calls.append({"kind": kind, "line": getattr(item, "lineno", None), "hosts": hosts})

    return sorted(calls, key=lambda item: (int(item["line"] or 0), str(item["kind"])))


def _egress_semantics(
    repo_root: Path,
    overlay: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    classifications = {
        str(item["module"]): item for item in overlay.get("egress_classifications", []) if item.get("module")
    }

    for root in (repo_root / "backend", repo_root / "services"):
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            rel = str(path.relative_to(repo_root)).replace("\\", "/")
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except (OSError, SyntaxError):
                continue
            calls = _network_calls(tree)
            if not calls:
                continue

            module = _module_for_path(repo_root, path)
            source_node = f"py:{module}"
            sink_id = f"egress:{module}"
            review = classifications.get(module, {})
            classification = str(review.get("classification") or "unclassified")
            target = str(review.get("target") or "external:unresolved-egress")
            reason = review.get("reason")
            hosts = sorted({host for call in calls for host in call.get("hosts", [])})

            node: dict[str, Any] = {
                "id": sink_id,
                "type": "network_egress_sink",
                "source": rel,
                "classification": classification,
                "calls": calls,
                "hosts": hosts,
            }
            if reason:
                node["classification_reason"] = str(reason)
            nodes.append(node)
            edges.append({"from": source_node, "to": sink_id, "type": "network_call", "evidence": rel})
            edges.append(
                {
                    "from": sink_id,
                    "to": target,
                    "type": "governed_http" if classification == "governed_authority" else "direct_network_egress",
                    "evidence": rel,
                }
            )

            if classification in {"known_violation", "unclassified"}:
                findings.append(
                    {
                        "id": f"egress-ungoverned:{module}",
                        "category": "external-egress",
                        "severity": "high" if classification == "known_violation" else "medium",
                        "summary": f"Production module {module} opens network egress outside the governed authority",
                        "evidence": [rel],
                        "related_nodes": [source_node, sink_id, target],
                        "blocking": classification == "unclassified",
                        "classification": classification,
                        "reason": str(reason) if reason else None,
                    }
                )

    return nodes, edges, findings


def _apply_acknowledgements(findings: list[dict[str, Any]], overlay: dict[str, Any]) -> list[dict[str, Any]]:
    acknowledgements = {str(item["id"]): item for item in overlay.get("acknowledged_findings", []) if item.get("id")}
    result: list[dict[str, Any]] = []
    for finding in findings:
        item = dict(finding)
        acknowledgement = acknowledgements.get(str(item["id"]))
        item["acknowledged"] = acknowledgement is not None
        if acknowledgement is not None:
            item["acknowledgement"] = {key: value for key, value in acknowledgement.items() if key != "id"}
        result.append(item)
    return sorted(result, key=lambda item: str(item["id"]))


def collect_semantic_inventory(repo_root: Path, overlay: dict[str, Any]) -> dict[str, Any]:
    db_nodes, db_edges, db_findings = _rls_semantics(repo_root, overlay)
    egress_nodes, egress_edges, egress_findings = _egress_semantics(repo_root, overlay)
    overlay_findings = [dict(item) for item in overlay.get("semantic_findings", [])]
    findings = _apply_acknowledgements(
        [*db_findings, *egress_findings, *overlay_findings],
        overlay,
    )
    return {
        "nodes": [*db_nodes, *egress_nodes],
        "edges": [*db_edges, *egress_edges],
        "findings": findings,
    }
