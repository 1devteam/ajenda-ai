#!/usr/bin/env python3
"""Draft ASCII v2 projection for Ajenda's canonical dependency graph.

This is a non-authoritative machine-ingestion projection. The canonical JSON graph
remains the source-backed artifact. ASCII v2 dictionary-encodes source paths,
node types, and relation types, then uses fixed-width node/relation codes for the
edge stream.

The projection intentionally carries topology only:
- node id
- node type
- source path
- edge source / relation / target

Evidence, invariants, semantic findings, runtime inventories, and other residual
facts remain in the canonical JSON artifact for targeted drill-down.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from build_dependency_graph import build_graph

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "artifacts" / "dependency-graph.ascii.v2.txt"
_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_EDGE_CHUNK = 4096


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _width(count: int) -> int:
    if count <= 1:
        return 1
    width = 1
    capacity = len(_ALPHABET)
    while capacity < count:
        width += 1
        capacity *= len(_ALPHABET)
    return width


def _code(index: int, width: int) -> str:
    if index < 0:
        raise ValueError("index must be non-negative")
    base = len(_ALPHABET)
    chars = [_ALPHABET[0]] * width
    value = index
    for offset in range(width - 1, -1, -1):
        chars[offset] = _ALPHABET[value % base]
        value //= base
    if value:
        raise ValueError("index exceeds code width")
    return "".join(chars)


def _escape(value: object) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace("|", "\\p").replace("\n", "\\n").replace("\r", "\\r")


def _unescape(value: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        if index + 1 >= len(value):
            raise ValueError("trailing escape in ASCII v2 graph")
        marker = value[index + 1]
        if marker == "\\":
            out.append("\\")
        elif marker == "p":
            out.append("|")
        elif marker == "n":
            out.append("\n")
        elif marker == "r":
            out.append("\r")
        else:
            raise ValueError(f"unknown ASCII v2 escape: {marker}")
        index += 2
    return "".join(out)


def _rank(values: list[str]) -> list[str]:
    counts = Counter(values)
    return [
        value
        for value, _count in sorted(
            counts.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]


def encode_graph_ascii_v2(graph: dict[str, Any]) -> str:
    """Encode Ajenda topology into deterministic ASCII v2."""

    nodes = sorted(
        (dict(node) for node in graph.get("nodes") or []),
        key=lambda node: str(node.get("id") or ""),
    )
    edges = sorted(
        (dict(edge) for edge in graph.get("edges") or []),
        key=lambda edge: (
            str(edge.get("from") or ""),
            str(edge.get("to") or ""),
            str(edge.get("type") or ""),
        ),
    )

    node_ids = [str(node.get("id") or "") for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("ASCII v2 requires unique node ids")
    node_index = {node_id: index for index, node_id in enumerate(node_ids)}

    missing = sorted(
        {
            endpoint
            for edge in edges
            for endpoint in (str(edge.get("from") or ""), str(edge.get("to") or ""))
            if endpoint not in node_index
        }
    )
    if missing:
        raise ValueError(f"ASCII v2 has undefined edge endpoints: {', '.join(missing)}")

    node_types = _rank([str(node.get("type") or "") for node in nodes])
    relation_types = _rank([str(edge.get("type") or "") for edge in edges])
    sources = _rank([str(node.get("source") or "") for node in nodes if str(node.get("source") or "")])

    node_width = _width(len(nodes))
    type_width = _width(len(node_types))
    relation_width = _width(len(relation_types))
    source_width = _width(len(sources) + 1)

    type_index = {value: index for index, value in enumerate(node_types)}
    relation_index = {value: index for index, value in enumerate(relation_types)}
    source_index = {value: index + 1 for index, value in enumerate(sources)}
    graph_sha = hashlib.sha256(_canonical_bytes(graph)).hexdigest()

    lines = [
        "G2"
        f"|n={len(nodes)}"
        f"|e={len(edges)}"
        f"|s={len(sources)}"
        f"|nt={len(node_types)}"
        f"|rt={len(relation_types)}"
        f"|nw={node_width}"
        f"|sw={source_width}"
        f"|tw={type_width}"
        f"|rw={relation_width}"
        "|d=c>d"
        f"|h={graph_sha}",
    ]

    for index, value in enumerate(node_types):
        lines.append(f"T{_code(index, type_width)}={_escape(value)}")
    for index, value in enumerate(relation_types):
        lines.append(f"R{_code(index, relation_width)}={_escape(value)}")
    for index, value in enumerate(sources, start=1):
        lines.append(f"S{_code(index, source_width)}={_escape(value)}")

    missing_source_code = _code(0, source_width)
    for index, node in enumerate(nodes):
        source = str(node.get("source") or "")
        fields = [
            _escape(node.get("id")),
            _code(type_index[str(node.get("type") or "")], type_width),
            _code(source_index[source], source_width) if source else missing_source_code,
        ]
        lines.append(f"N{_code(index, node_width)}=" + "|".join(fields))

    stream = "".join(
        _code(node_index[str(edge.get("from") or "")], node_width)
        + _code(relation_index[str(edge.get("type") or "")], relation_width)
        + _code(node_index[str(edge.get("to") or "")], node_width)
        for edge in edges
    )
    if stream:
        lines.append("E=" + stream[:_EDGE_CHUNK])
        for offset in range(_EDGE_CHUNK, len(stream), _EDGE_CHUNK):
            lines.append("E+" + stream[offset : offset + _EDGE_CHUNK])
    else:
        lines.append("E=")

    return "\n".join(lines) + "\n"


def decode_graph_ascii_v2(text: str) -> dict[str, Any]:
    """Decode the topology projection for lossless verification."""

    lines = text.splitlines()
    if not lines or not lines[0].startswith("G2|"):
        raise ValueError("unsupported ASCII v2 header")

    header: dict[str, str] = {}
    for part in lines[0].split("|")[1:]:
        key, value = part.split("=", 1)
        header[key] = value

    node_count = int(header["n"])
    edge_count = int(header["e"])
    node_width = int(header["nw"])
    source_width = int(header["sw"])
    relation_width = int(header["rw"])

    node_types: dict[str, str] = {}
    relation_types: dict[str, str] = {}
    sources: dict[str, str] = {}
    nodes_by_code: dict[str, dict[str, str]] = {}
    edge_chunks: list[str] = []

    for line in lines[1:]:
        if line.startswith("T"):
            code, value = line[1:].split("=", 1)
            node_types[code] = _unescape(value)
        elif line.startswith("R"):
            code, value = line[1:].split("=", 1)
            relation_types[code] = _unescape(value)
        elif line.startswith("S"):
            code, value = line[1:].split("=", 1)
            sources[code] = _unescape(value)
        elif line.startswith("N"):
            code, raw = line[1:].split("=", 1)
            node_id, type_code, source_code = raw.split("|", 2)
            node = {
                "id": _unescape(node_id),
                "type": node_types[type_code],
            }
            if source_code != _code(0, source_width):
                node["source"] = sources[source_code]
            nodes_by_code[code] = node
        elif line.startswith("E="):
            edge_chunks.append(line[2:])
        elif line.startswith("E+"):
            edge_chunks.append(line[2:])
        else:
            raise ValueError(f"unknown ASCII v2 row: {line[:16]}")

    if len(nodes_by_code) != node_count:
        raise ValueError("ASCII v2 node count mismatch")

    edge_stream = "".join(edge_chunks)
    record_width = node_width + relation_width + node_width
    if len(edge_stream) != edge_count * record_width:
        raise ValueError("ASCII v2 edge stream length mismatch")

    edges: list[dict[str, str]] = []
    for offset in range(0, len(edge_stream), record_width):
        record = edge_stream[offset : offset + record_width]
        source_code = record[:node_width]
        relation_code = record[node_width : node_width + relation_width]
        target_code = record[node_width + relation_width :]
        edges.append(
            {
                "from": nodes_by_code[source_code]["id"],
                "to": nodes_by_code[target_code]["id"],
                "type": relation_types[relation_code],
            }
        )

    nodes = [_code(index, node_width) for index in range(node_count)]
    return {
        "schema_version": "ajenda-ascii-topology-v2-draft",
        "direction": header["d"],
        "source_graph_sha256": header["h"],
        "nodes": [nodes_by_code[code] for code in nodes],
        "edges": edges,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preview-lines", type=int, default=0)
    args = parser.parse_args()

    graph = build_graph()
    encoded = encode_graph_ascii_v2(graph)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="ascii")

    canonical_bytes = len(_canonical_bytes(graph))
    ascii_bytes = len(encoded.encode("ascii"))
    reduction = 0.0 if canonical_bytes == 0 else (1.0 - ascii_bytes / canonical_bytes) * 100.0
    print(
        "Ajenda ASCII v2 draft: "
        f"{len(graph.get('nodes') or [])} nodes, "
        f"{len(graph.get('edges') or [])} edges, "
        f"json_bytes={canonical_bytes}, ascii_bytes={ascii_bytes}, "
        f"byte_reduction={reduction:.2f}%"
    )
    if args.preview_lines > 0:
        for line in encoded.splitlines()[: args.preview_lines]:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
