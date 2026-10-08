from __future__ import annotations

import json
from pathlib import Path

import scripts.validation.graph_filesystem_frontier as frontier


def _spec() -> dict:
    return json.loads(Path("docs/frontier/ajenda-filesystem-shadow.v2.json").read_text(encoding="utf-8"))


def test_frontier_candidate_identity_is_exact(monkeypatch) -> None:
    spec = _spec()
    spec["candidate_paths"] = ["current_layout_baseline"]

    monkeypatch.setattr(frontier, "validate_frontier_spec", lambda _spec: [])

    try:
        frontier.build_shadow(spec)
    except ValueError as exc:
        assert "candidate_paths" in str(exc)
    else:
        raise AssertionError("candidate mismatch must fail closed")


def test_machine_shadow_federates_graft_evidence(monkeypatch) -> None:
    graph = {
        "schema_version": "1.4",
        "nodes": [
            {
                "id": "py:backend.services.account_service",
                "type": "python_module",
                "source": "backend/services/account_service.py",
            },
            {
                "id": "py:backend.services.tools.sample",
                "type": "python_module",
                "source": "backend/services/tools/sample.py",
            },
        ],
        "edges": [
            {
                "from": "py:backend.services.account_service",
                "to": "py:backend.services.tools.sample",
                "type": "imports",
                "evidence": "backend/services/account_service.py",
            }
        ],
    }
    monkeypatch.setattr(frontier, "validate_frontier_spec", lambda _spec: [])
    monkeypatch.setattr(frontier, "build_graph", lambda: graph)
    monkeypatch.setattr(
        frontier,
        "audit_graph",
        lambda _graph: {"static_cycles": []},
    )
    monkeypatch.setattr(
        frontier,
        "build_projection",
        lambda: {
            "candidate_files": [
                {
                    "source": "backend/services/account_service.py",
                    "package_affinity": [{"package": "tools", "score": 6, "edge_count": 1}],
                }
            ]
        },
    )
    monkeypatch.setattr(
        frontier,
        "adjudicate_runtime_contracts_with_consumption",
        lambda _graph: {
            "metrics": {"candidate_count": 1, "satisfied_count": 1},
            "results": [
                {
                    "witness_sources": ["backend/services/account_service.py"],
                }
            ],
        },
    )
    monkeypatch.setattr(
        frontier,
        "validate_conformance",
        lambda: {"status": "passed", "node_count": 24},
    )

    artifact = frontier.build_shadow(_spec())

    assert artifact["k"] == "graft_frontier_filesystem_shadow"
    assert artifact["auth"] == {
        "runtime": False,
        "source_mutation": False,
        "promotion": False,
    }
    assert artifact["cn"] == list(frontier.CANDIDATES)
    assert len(artifact["c"]) == 3
    assert "backend/services/account_service.py" in artifact["f"]
    assert "runtime_contract_consumption" in artifact["t"]
    assert artifact["ev"]
    assert artifact["af"]
    assert artifact["fg"]["runtime_contract_candidates"] == 1
    assert artifact["fg"]["graft1st_status"] == "passed"
