# Operational Definitions and Classification Rubric

**Version:** 0.1 — 2026-08-24

## Change
A merged pull request that modifies the Ajenda production system, its executable contracts, tests/proofs, deployment behavior, or architecture-relevant configuration. Research-only study instrumentation is excluded.

## Origin PR
A PR whose introduced behavior or changed contract is later corrected, or whose change exposes a pre-existing defect that becomes the subject of corrective work.

## Corrective PR
A later PR whose purpose includes restoring intended behavior, closing an unintended architectural hole, repairing a regression, correcting an invalid assumption/contract, or reconciling state made inconsistent by an earlier change.

## Causal repair edge
A directed relationship `A -> B` meaning evidence supports that change A introduced behavior that made corrective change B necessary.

## Exposure edge
A directed relationship `A ~> B` meaning A did not create the underlying defect but activated, revealed, or made observable a pre-existing weakness corrected by B.

## Planned dependency
A later PR intentionally builds additional capability on an earlier PR without repairing unintended behavior. This is not corrective rework.

## Feature evolution
A later change reflects a new or changed requirement rather than correction of the earlier implementation. This is not corrective rework.

## Corrective cascade
A connected directed structure containing at least one causal-repair or exposure edge and at least one corrective descendant.

## Cascade depth
Maximum number of corrective causal/exposure edges from an origin PR to a descendant within the cascade.

## Cascade width
Number of distinct direct corrective descendants from a node, and, when reported for a full cascade, the number of corrective descendants across the structure.

## Corrective descendant count
Number of later PRs reachable from an origin PR through corrective causal/exposure edges.

## PR distance to correction
Difference in PR number between an origin and correction. Report alongside elapsed wall-clock time because PR number is only an ordering proxy.

## Time to architectural closure
Elapsed time from origin merge until the final known corrective descendant in the identified cascade is merged. This is retrospective and may be censored if later corrections remain possible.

## Architectural blast radius
The set of architecture-relevant nodes, edges, contracts, boundaries, proofs, configuration, persistence, runtime paths, and external interactions whose correctness can be materially affected by a proposed change.

## Reasoning/change scope
The system surface evidenced as inspected, modified, tested, or explicitly considered by the original change. Absence of evidence is not automatically proof that a developer/AI did not reason about something; uncertainty must be recorded.

## Scope/blast-radius mismatch
A condition where later evidence demonstrates that architecture-relevant affected surface existed outside the original PR's evidenced reasoning/validation scope.

## First-pass architectural completeness
For a change with retrospectively identified architecture-relevant obligations, the proportion resolved correctly in the origin PR rather than in corrective descendants. Exact computation requires an auditable obligation set and must not be estimated from intuition.

## Corrective rework
Engineering activity primarily required to repair unintended consequences, incomplete contracts, regressions, or architectural inconsistencies attributable to prior changes. Intentional product evolution is excluded.

## Architectural hotspot
A component, contract, boundary, or relationship with elevated combination of dependency centrality, change centrality, and corrective/failure centrality.

## Local correctness
A change satisfies the tests/contracts within its immediate validated scope.

## System coherence
Relevant architectural contracts and invariants remain mutually consistent across the full affected blast radius.

## Evidence grades

### A — Direct
Explicit textual or executable evidence links the correction to the originating change/PR.

### B — Strong inferred
Diff/ancestry/contract evidence establishes the relationship without an explicit textual statement.

### C — Exposure
The earlier change reveals or activates a pre-existing weakness rather than creating it.

### U — Uncertain
Evidence is insufficient to distinguish causation, exposure, evolution, or coincidence. Exclude from headline causal counts.

## Required edge record

Each candidate edge should record:
- origin PR;
- corrective PR;
- edge class;
- evidence grade;
- explicit references/quotes where available;
- merge ancestry;
- affected files/components/contracts;
- defect/invariant description;
- introduced vs exposed determination;
- alternative explanation;
- reviewer/classifier confidence;
- notes on ambiguity.
