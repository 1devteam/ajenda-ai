from scripts.validation.graph_ascii_v2 import decode_graph_ascii_v2, encode_graph_ascii_v2


def test_ascii_v2_round_trips_topology_with_source_dictionary() -> None:
    graph = {
        "schema_version": "test",
        "nodes": [
            {"id": "py:a", "type": "python_module", "source": "backend/services/a.py"},
            {"id": "fn:a:f", "type": "python_function", "source": "backend/services/a.py"},
            {"id": "py:b", "type": "python_module", "source": "backend/services/b.py"},
        ],
        "edges": [
            {"from": "py:a", "to": "py:b", "type": "imports", "evidence": "backend/services/a.py"},
            {"from": "fn:a:f", "to": "py:b", "type": "calls_function", "evidence": "backend/services/a.py"},
        ],
    }

    encoded = encode_graph_ascii_v2(graph)
    decoded = decode_graph_ascii_v2(encoded)

    assert encoded.isascii()
    assert encoded.startswith("G2|")
    assert encoded.count("backend/services/a.py") == 1
    assert decoded["direction"] == "c>d"
    assert decoded["nodes"] == [
        {"id": "fn:a:f", "type": "python_function", "source": "backend/services/a.py"},
        {"id": "py:a", "type": "python_module", "source": "backend/services/a.py"},
        {"id": "py:b", "type": "python_module", "source": "backend/services/b.py"},
    ]
    assert decoded["edges"] == [
        {"from": "fn:a:f", "to": "py:b", "type": "calls_function"},
        {"from": "py:a", "to": "py:b", "type": "imports"},
    ]


def test_ascii_v2_keeps_residual_facts_out_of_fast_topology() -> None:
    graph = {
        "nodes": [{"id": "a", "type": "runtime", "source": "backend/a.py"}],
        "edges": [],
        "semantic_findings": [{"id": "finding:1", "summary": "not duplicated"}],
        "invariants": [{"id": "inv:1"}],
    }

    encoded = encode_graph_ascii_v2(graph)

    assert "finding:1" not in encoded
    assert "inv:1" not in encoded
