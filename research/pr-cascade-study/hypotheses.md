# Initial Hypotheses

**Recorded before exhaustive classification:** 2026-08-24

These are hypotheses, not findings.

## H1 — Corrective cascade hypothesis

A non-trivial portion of merged software changes will have corrective descendants where an earlier change introduced or exposed a contract, boundary, ordering, ownership, authority, data, or integration problem requiring later repair.

## H2 — Scope/blast-radius mismatch hypothesis

Corrective-cascade probability increases when the reasoning and validation scope used for a change covers less of the system than the change's actual architectural blast radius.

## H3 — Recursive correction hypothesis

Locally scoped corrections can themselves generate corrective descendants when they repair a symptom without resolving the full affected architectural relationship.

## H4 — Hotspot concentration hypothesis

Corrective cascades will be disproportionately concentrated around high-impact architectural boundaries rather than uniformly distributed across the repository.

## H5 — Passing-tests/system-incompleteness hypothesis

A meaningful subset of cascade-origin PRs will have passing local/targeted tests despite later evidence that the change was system-incomplete, demonstrating a distinction between local test correctness and architectural completeness.

## H6 — Context-boundary hypothesis

A meaningful share of observed failures will be attributable less to inability to generate locally correct code and more to selecting an insufficiently broad representation/context for the change.

## H7 — Corrective redundancy hypothesis

Some measurable fraction of historical engineering activity will consist of repeated rediscovery and correction of consequences of earlier changes rather than net-new capability development.

## H8 — Graph-assisted completeness hypothesis

Graph-assisted change planning will increase first-pass architectural completeness and reduce corrective descendant count, cascade depth, and time-to-closure compared with the pre-graph baseline, subject to change size and complexity.

## H9 — Coherence convergence hypothesis

If graph-assisted corrections repair architectural classes/invariants rather than isolated symptoms, the stock of hidden large-scale incoherence should decline over successive graph-assisted production changes, producing fewer and shallower related corrective cascades.

## H10 — Minimum sufficient context hypothesis

A dependency/semantic graph can be used to identify a bounded reasoning surface that is substantially smaller than 'the entire repository' while retaining enough architectural context for coherent change planning.

## H11 — Procedure-versus-representation hypothesis

Procedural instructions such as reading broadly, considering system-wide impact, and checking edge cases improve development discipline but cannot fully substitute for an explicit structural representation of system relationships.

## H12 — Architecture-aware scope hypothesis

The effective alternative to uniformly small or uniformly large PRs is architecture-aware change sizing: change scope should be derived from the affected architectural dependency boundary rather than from a predetermined preference for small implementation units.
