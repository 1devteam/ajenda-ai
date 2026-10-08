#!/usr/bin/env python3
"""Benchmark Ajenda canonical graph ingestion against the ASCII v2 draft.

This is an ingestion-cost experiment, not a production tokenizer claim.
It uses tiktoken o200k_base as a reproducible GPT-family proxy and refuses to
report compression unless the ASCII v2 topology decodes to the same ordered
node/source/type projection and typed-edge stream as the canonical graph.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import tiktoken

from build_dependency_graph import build_graph
from graph_ascii_v2 import decode_graph_ascii_v2, encode_graph_ascii_v2

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "graph-ingestion-token-benchmark.v1.json"
TOKENIZER = "o200k_base"


def _pretty_json(graph: dict[str, Any]) -> str:
    return json.dumps(graph, indent=2, sort_keys=True) + "\n"


def _compact_json(graph: dict[str, Any]) -> str:
    return json.dumps(graph, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _node_projection(graph: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for node in sorted(graph.get("nodes") or [], key=lambda item: str(item.get("id") or "")):
        row = {
            "id": str(node.get("id") or ""),
            "type": str(node.get("type") or ""),
        }
        source = node.get("source")
        if isinstance(source, str) and source:
            row["source"] = source
        rows.append(row)
    return rows


def _edge_projection(graph: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "from": str(edge.get("from") or ""),
            "to": str(edge.get("to") or ""),
            "type": str(edge.get("type") or ""),
        }
        for edge in sorted(
            graph.get("edges") or [],
            key=lambda item: (
                str(item.get("from") or ""),
                str(item.get("to") or ""),
                str(item.get("type") or ""),
            ),
        )
    ]


def _measure(text: str, *, encoding: Any) -> dict[str, int]:
    return {
        "chars": len(text),
        "bytes": len(text.encode("utf-8")),
        "tokens": len(encoding.encode(text)),
    }


def _reduction(candidate: int, baseline: int) -> float:
    if baseline <= 0:
        return 0.0
    return round((1.0 - candidate / baseline) * 100.0, 4)


def _ratio(baseline: int, candidate: int) -> float | None:
    if candidate <= 0:
        return None
    return round(baseline / candidate, 4)


def build_benchmark(graph: dict[str, Any] | None = None) -> dict[str, Any]:
    graph = graph or build_graph()
    ascii_v2 = encode_graph_ascii_v2(graph)
    decoded = decode_graph_ascii_v2(ascii_v2)

    canonical_nodes = _node_projection(graph)
    canonical_edges = _edge_projection(graph)
    if decoded["nodes"] != canonical_nodes:
        raise ValueError("ASCII v2 node/source/type topology is not lossless")
    if decoded["edges"] != canonical_edges:
        raise ValueError("ASCII v2 typed edge topology is not lossless")

    encoding = tiktoken.get_encoding(TOKENIZER)
    payloads = {
        "emitted_pretty_json": _pretty_json(graph),
        "compact_json": _compact_json(graph),
        "ascii_v2": ascii_v2,
    }
    measured = {name: _measure(text, encoding=encoding) for name, text in payloads.items()}
    pretty = measured["emitted_pretty_json"]
    compact = measured["compact_json"]
    ascii_measure = measured["ascii_v2"]

    return {
        "schema_version": "1.0",
        "artifact_kind": "graft_ingestion_token_benchmark",
        "subject": "Ajenda canonical dependency graph",
        "tokenizer": {
            "library": "tiktoken",
            "encoding": TOKENIZER,
            "claim_scope": "reproducible GPT-family proxy; not private GPT-5.6 production tokenizer",
        },
        "fidelity": {
            "node_source_type_projection_equal": True,
            "typed_edge_stream_equal": True,
            "node_count": len(canonical_nodes),
            "edge_count": len(canonical_edges),
            "ascii_source_graph_sha256": decoded["source_graph_sha256"],
        },
        "measurements": measured,
        "comparisons": {
            "ascii_vs_emitted_pretty_json": {
                "byte_reduction_percent": _reduction(ascii_measure["bytes"], pretty["bytes"]),
                "token_reduction_percent": _reduction(ascii_measure["tokens"], pretty["tokens"]),
                "token_ratio": _ratio(pretty["tokens"], ascii_measure["tokens"]),
            },
            "ascii_vs_compact_json": {
                "byte_reduction_percent": _reduction(ascii_measure["bytes"], compact["bytes"]),
                "token_reduction_percent": _reduction(ascii_measure["tokens"], compact["tokens"]),
                "token_ratio": _ratio(compact["tokens"], ascii_measure["tokens"]),
            },
            "compact_vs_emitted_pretty_json": {
                "byte_reduction_percent": _reduction(compact["bytes"], pretty["bytes"]),
                "token_reduction_percent": _reduction(compact["tokens"], pretty["tokens"]),
                "token_ratio": _ratio(pretty["tokens"], compact["tokens"]),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    artifact = build_benchmark()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    measurements = artifact["measurements"]
    comparisons = artifact["comparisons"]
    print(
        "AJENDA_TOKEN_BENCH "
        f"nodes={artifact['fidelity']['node_count']} "
        f"edges={artifact['fidelity']['edge_count']} "
        f"tokenizer={artifact['tokenizer']['encoding']}"
    )
    for name in ("emitted_pretty_json", "compact_json", "ascii_v2"):
        item = measurements[name]
        print(f"TOKEN_SURFACE {name} bytes={item['bytes']} chars={item['chars']} tokens={item['tokens']}")
    for name, comparison in comparisons.items():
        print(
            f"TOKEN_COMPARE {name} "
            f"byte_reduction={comparison['byte_reduction_percent']:.4f}% "
            f"token_reduction={comparison['token_reduction_percent']:.4f}% "
            f"token_ratio={comparison['token_ratio']}"
        )
    print("TOKEN_FIDELITY nodes_sources_types=equal typed_edges=equal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
