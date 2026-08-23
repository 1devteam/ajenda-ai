# Ajenda Canonical Dependency Graph

## Purpose

The dependency graph is the repository-level source of truth for change-impact analysis. It combines generated source dependencies with semantic architectural relationships that cannot be recovered reliably from imports alone.

The graph is intended to answer five questions before a change is merged:

1. What does the changed component depend on?
2. What depends on the changed component?
3. Which runtime, security, data, configuration, or external-service boundaries are in the blast radius?
4. Which architectural invariants apply?
5. Which tests and proof obligations should be reviewed?

## Canonical inputs

`backend/**/*.py` supplies generated Python module/import nodes and edges.

`frontend/src/**/*.ts` and `frontend/src/**/*.tsx` supply generated frontend module/import nodes and edges for relative source imports.

`docs/contracts/dependency-graph.overlay.v1.json` supplies semantic nodes, semantic edges, and architectural invariants. The overlay is intentionally explicit: runtime authority, queueing, RLS, OAuth, credential resolution, network egress, configuration, and HTTP contracts are not equivalent to source imports and must retain their own edge types.

## Generator

Run:

`python scripts/validation/build_dependency_graph.py`

The default output is `docs/architecture/dependency-graph.v1.json`.

CI runs the same generator and uploads the resulting JSON as the `canonical-dependency-graph` workflow artifact whenever graph-sensitive source or graph-contract files change.

## Graph model

Every node has a stable `id` and `type`. Static source nodes also carry a repository `source` path.

Every edge has `from`, `to`, `type`, and `evidence` fields. Edge type is semantically meaningful. Examples include `imports`, `calls`, `uses`, `reads_config`, `activates_rls_session`, `queue_claim`, `authorizes_before_egress`, `governed_http`, and `http_contract`.

The graph must not collapse those edge types into a generic "depends on" relationship. A source import, an authorization decision, an HTTP contract, and a database isolation boundary create different failure modes and different proof obligations.

## Metrics

The generated graph calculates:

- total node count
- total edge count
- top fan-in nodes
- top fan-out nodes
- strongly connected components in the static import graph

Fan-in is the number of direct graph edges entering a node. Fan-out is the number leaving it. These measurements are indicators, not automatic risk scores. Security choke points and orchestration authorities may be high-risk even when their raw fan-in is small.

## Invariants

The semantic overlay records architectural invariants and their current status. Status is deliberately explicit. An invariant may be enforced, enforced doctrine, an enforced design boundary, an enforced meta-invariant, or known policy drift.

Known policy drift must not be silently converted into an enforced rule until implementation and declared architecture agree.

## Relationship to the PR invariant classifier

`pr_invariant_classifier.py` is the PR gate. The canonical dependency graph is the architecture model behind increasingly precise blast-radius analysis.

The intended long-term flow is:

PR diff -> changed graph nodes -> direct/transitive dependencies -> affected semantic boundaries -> applicable invariants -> required tests/proofs.

The graph describes the system. The classifier decides what a particular change must prove.

## Maintenance rule

Generated source edges must come from source, not manual editing.

Semantic runtime/authority edges must be supported by repository evidence and added to the overlay when architecture changes.

A new runtime authority, external provider, security boundary, credential path, queue authority, or cross-layer contract should update the semantic overlay in the same PR.
