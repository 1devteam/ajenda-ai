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

`backend/**/*.py` supplies generated Python module/import nodes and edges for the primary application/runtime package.

`services/**/*.py` supplies generated Python module/import nodes and edges for standalone executable services such as the HubSpot CRM adapter.

`frontend/src/**/*.ts` and `frontend/src/**/*.tsx` supply generated frontend module/import nodes and edges for relative source imports.

`tests/**/*.py` supplies generated test-to-production impact edges for direct imports of backend or standalone-service modules.

`docs/contracts/dependency-graph.overlay.v1.json` supplies semantic nodes, semantic edges, and architectural invariants. The overlay is intentionally explicit: runtime authority, queueing, RLS, OAuth, credential resolution, network egress, configuration, and HTTP contracts are not equivalent to source imports and must retain their own edge types.

## Generator and artifact lifecycle

Run:

`python scripts/validation/build_dependency_graph.py`

The default local output is `docs/architecture/dependency-graph.v1.json`.

That generated JSON is intentionally not committed. The durable source of truth is the generator plus the semantic overlay; the full graph is a deterministic build artifact. CI runs the same generator and uploads the resulting JSON as the `canonical-dependency-graph` workflow artifact whenever graph-sensitive source or graph-contract files change.

This avoids large generated-file diffs while preserving a reproducible graph for every relevant revision.

## Graph model

Every node has a stable `id` and `type`. Static source and test nodes also carry a repository `source` path.

Every edge has `from`, `to`, `type`, and `evidence` fields. Edge type is semantically meaningful. Examples include `imports`, `tests`, `calls`, `uses`, `reads_config`, `activates_rls_session`, `credential_authority`, `egress_authority`, `governed_http`, and `http_contract`.

The graph must not collapse those edge types into a generic "depends on" relationship. A source import, a test relationship, an authorization decision, an HTTP contract, and a database isolation boundary create different failure modes and different proof obligations.

Source-backed semantic relationships use the generated source-node IDs instead of duplicate semantic nodes. This keeps centrality and blast-radius calculations attached to one canonical representation of each source component.

### Dependency direction

Canonical graph direction is `consumer -> dependency`.

If `A -> B`, component A uses, imports, calls, configures, or otherwise depends on B.

That direction gives change-impact traversal precise meanings:

- reverse traversal from a changed node finds upstream consumers: components whose behavior may be affected by that change
- forward traversal from a changed node finds downstream prerequisites: components or boundaries the changed component relies on

Upstream consumers and downstream prerequisites must not be merged into one unlabeled list. They represent different engineering questions.

## Change-impact analyzer

Run:

`python scripts/validation/graph_impact_analysis.py --changed-file backend/app/config.py --json`

For CI, the analyzer discovers the actual PR or push diff automatically.

The generated `artifacts/graph-impact-report.json` contains:

- changed graph nodes
- changed repository paths that could not be mapped to graph nodes
- transitive upstream consumers
- transitive downstream dependencies/prerequisites
- impacted tests
- affected semantic runtime/security/external nodes
- semantic prerequisites
- relevant architectural invariants
- existing PR invariant-classifier risk domains
- summary counts

Impacted tests are selected from changed production nodes plus upstream production consumers. A test attached only to an unrelated downstream prerequisite is not automatically considered impacted merely because the changed component depends on that prerequisite.

Unmapped changed files are retained explicitly rather than silently discarded. Configuration, deployment, documentation, migration, or workflow changes may still carry architectural risk even when no source node represents them directly.

The analyzer supports an optional `--max-depth` for bounded exploration. CI uses full transitive traversal by default.

## Metrics

The generated graph calculates:

- total node count
- total edge count
- edge counts by type
- top fan-in nodes
- top production fan-in nodes, excluding test edges
- top fan-out nodes
- strongly connected components in the static import graph

Fan-in is the number of direct graph edges entering a node. Fan-out is the number leaving it. These measurements are indicators, not automatic risk scores. Security choke points and orchestration authorities may be high-risk even when their raw fan-in is small.

## Invariants

The semantic overlay records architectural invariants and their current status. Status is deliberately explicit. An invariant may be enforced, enforced doctrine, an enforced design boundary, an enforced meta-invariant, or known policy drift.

Known policy drift must not be silently converted into an enforced rule until implementation and declared architecture agree.

The impact analyzer considers an invariant relevant when changed or traversed graph context intersects source evidence or explicit `applies_to` nodes recorded for that invariant.

## Relationship to the PR invariant classifier

`pr_invariant_classifier.py` remains the deterministic PR gate for proof obligations and known risk-domain rules. `graph_impact_analysis.py` provides structural blast-radius evidence behind those decisions.

The intended flow is:

PR diff -> changed graph nodes -> upstream consumers + downstream prerequisites -> affected semantic boundaries -> applicable invariants -> relevant tests -> required proofs.

The graph describes the system. The impact analyzer describes structural change reachability. The classifier decides what a particular change must prove.

## Maintenance rule

Generated source and test-impact edges must come from source, not manual editing.

Semantic runtime/authority edges must be supported by repository evidence and added to the overlay when architecture changes.

A new runtime authority, external provider, security boundary, credential path, queue authority, standalone executable service, or cross-layer contract should update the semantic overlay in the same PR.
