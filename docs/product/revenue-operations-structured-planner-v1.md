# Revenue Operations Structured Planner V1

**Status:** implemented behind injection; disabled by default; provider benchmark pending  
**Schema:** `PLANNER_PROPOSAL_SCHEMA_VERSION = 1`  
**Authority:** proposal only; never execution or approval authority

## Boundary

`backend/services/mission_composition/structured_planner.py` defines a typed proposal containing
the pinned know-how version, material-clause IDs, jobs, dependencies, artifact bindings,
assumptions, clarifications, success criteria, review points, and proposed budgets. Provider output
is parsed as strict JSON with `extra="forbid"`; markdown repair, prose extraction, and field guessing
are intentionally absent.

The OpenAI-compatible adapter requires an injected real model result. The generic text-generation
template fallback is rejected because echo text is not a planning result. User instructions and
provider/retrieved content are labeled untrusted data in the provider request.

## Deterministic acceptance

Before a proposal can influence composition, the validator requires:

- exact know-how ID/version and material-clause coverage;
- every deterministically required job to remain present;
- jobs to belong to the selected know-how and form an acyclic graph;
- artifact producer outputs and consumer inputs to exist in the current job catalog;
- required Gmail/HubSpot connections to be present;
- every always-review job to have a review point; and
- proposed budgets not to exceed an owner-approved know-how budget when one exists.

Validated proposals may alter the proposed job ordering/set within those constraints. They still
pass through ordinary deterministic ability resolution and compile only to a read-model graph.
Rejected provider output creates a sanitized `planner_validation` clarification and cannot make a
proposal ready.

## Persistence and proof

Composition records store the typed proposal and provider/model/instruction-hash provenance. They
never store model-supplied credentials or authorization. Unit proof covers invalid JSON,
extra/injected fields, claimed authority, clause omission, out-of-contract jobs, cycles, bad
artifact bindings, missing connectors, missing review, template fallback, and valid injected
proposal persistence.

Production use remains blocked until an owner-thresholded provider benchmark runs against sealed
held-out cases. No unit test or fake provider result is counted as that benchmark.
