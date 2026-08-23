# Graph Architecture Decision Manifest

## Purpose

`graph-architecture-decision.json` is the consolidated PR-facing decision artifact for Ajenda's canonical dependency graph system.

It does not replace the underlying graph, impact report, proof manifest, completeness report, PR invariant classifier, or the repository's authoritative CI gate. It composes their architecture evidence into one deterministic view for reviewers and automation.

The input chain is:

`PR diff -> graph impact -> proof selection -> completeness audit -> architecture decision manifest`

The raw inputs remain available as separate artifacts so reviewers can inspect the full evidence behind the decision.

## Run locally

Generate the prerequisite reports, then run:

`python scripts/validation/graph_architecture_decision.py --impact-report artifacts/graph-impact-report.json --proof-manifest artifacts/graph-proof-manifest.json --completeness-report artifacts/graph-completeness-report.json --json --output artifacts/graph-architecture-decision.json`

CI performs the same composition automatically in the canonical dependency-graph workflow.

## Dispositions

The manifest emits `decision.architecture_disposition` with one of three values.

### `clear`

No graph-derived architecture blocker or explicit human-review obligation was found.

`clear` does **not** mean the pull request is merge-ready. The manifest always emits:

- `merge_authorization: not-determined`
- `full_ci_required: true`

The existing PR gate remains the authority for lint, type checking, tests, migrations, builds, security checks, and other required merge evidence.

### `review-required`

The graph/proof system found an obligation that cannot be reduced to a deterministic automatic pass/fail result. Examples include:

- known architecture policy drift requiring human review
- unmapped changed files that the canonical graph does not yet model
- review-only runtime proof such as live provider/runtime validation

These obligations are emitted as `decision.review_reasons`.

### `blocked`

The graph decision cannot safely be treated as valid. Current blocking conditions include:

- canonical graph completeness integrity failure
- invalid proof-manifest gate taxonomy
- unsafe or nonexistent selected test paths
- other proof-manifest validation failures

A blocked decision exits non-zero in CI.

## Evidence fingerprints

The manifest records a SHA-256 fingerprint for each normalized JSON input:

- `artifacts/graph-impact-report.json`
- `artifacts/graph-proof-manifest.json`
- `artifacts/graph-completeness-report.json`

This makes the consolidated decision traceable to the exact reports it summarizes without duplicating their full payloads.

## Impact summary

The manifest includes a compact architecture-impact view:

- changed repository files
- changed graph node IDs and source paths
- unmapped changed files
- relevant invariant IDs
- classifier risk-domain IDs
- affected semantic boundary nodes
- semantic prerequisite nodes

The full transitive graph traversal remains in `graph-impact-report.json`.

## Proof summary

The manifest includes:

- selected proof-bundle IDs
- required test paths
- required CI gate categories
- review-only gates
- manual-review obligations
- selective-CI full-suite fallback state and reasons

The decision composer reuses the selective-CI proof-manifest validator. It therefore fails closed on unknown gates, unsafe paths, or selected test paths that do not exist in the repository.

## Completeness warnings

Topology observations are kept distinct from violations.

If the impacted graph context intersects a `semantic-only` relationship, the manifest records that relationship and emits a warning. `semantic-only` means the architectural relationship is explicitly evidenced but is not corroborated by static import reachability; it is not automatically drift.

If the impacted graph context intersects a static strongly connected component that crosses architectural boundaries, the manifest records the cycle and emits a warning. Cross-boundary cycles are architectural review evidence, not automatically a merge blocker.

This distinction prevents graph topology metrics from being misrepresented as policy or security violations.

## CI behavior

The canonical dependency-graph workflow produces five synchronized artifacts:

1. `docs/architecture/dependency-graph.v1.json`
2. `artifacts/graph-impact-report.json`
3. `artifacts/graph-proof-manifest.json`
4. `artifacts/graph-completeness-report.json`
5. `artifacts/graph-architecture-decision.json`

The completeness audit is allowed to write its report even when integrity fails. The architecture decision step then converts that condition into a machine-readable `blocked` disposition and fails the workflow. Artifact upload runs even after failure so the available evidence is retained for diagnosis.

## Authority boundary

The architecture decision manifest is an architecture-analysis control, not merge authority.

It must never be used to bypass required CI, branch protection, live-runtime requirements, security checks, or explicit human review. Future selective-CI work may consume the manifest, but any reduction of broad regression coverage requires separate evidence and policy approval.
