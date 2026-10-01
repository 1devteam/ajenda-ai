#!/usr/bin/env python3
"""Validate canonical ownership and compatibility for Ajenda's outcome graphs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_GRAPHS = {"semantic", "epistemic", "operational"}


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("manifest_version") != "1.0.0":
        errors.append("manifest_version must be 1.0.0")
    if manifest.get("authority_class") != "architecture_governance":
        errors.append("authority_class must be architecture_governance")
    graphs = manifest.get("graphs")
    if not isinstance(graphs, dict):
        return ["graphs must be an object"]
    if set(graphs) != EXPECTED_GRAPHS:
        errors.append(f"graphs must contain exactly {sorted(EXPECTED_GRAPHS)}")
    for name in EXPECTED_GRAPHS:
        graph = graphs.get(name)
        if not isinstance(graph, dict):
            errors.append(f"{name} graph must be an object")
            continue
        for field in ("owner", "version", "compatibility", "historical_read"):
            if not isinstance(graph.get(field), str) or not graph[field].strip():
                errors.append(f"{name}.{field} must be a non-empty string")
        sources = graph.get("source_of_truth")
        if not isinstance(sources, list) or not sources or not all(isinstance(item, str) for item in sources):
            errors.append(f"{name}.source_of_truth must be a non-empty list of paths")
    if manifest.get("grants_runtime_authority") is not False:
        errors.append("grants_runtime_authority must be false")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("docs/contracts/outcome-graph-ownership.v1.json"),
    )
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object")
        errors = validate_manifest(manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Outcome graph ownership: failed: {exc}")
        return 1
    if errors:
        print("Outcome graph ownership: failed")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Outcome graph ownership: passed (semantic, epistemic, operational)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
