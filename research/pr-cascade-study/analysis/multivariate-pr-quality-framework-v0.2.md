# Multivariate PR Quality & Graph-Effect Analysis Framework v0.2

**Status:** exploratory working framework; not an empirical finding  
**Supersedes:** v0.1 on the active research branch  
**Population reconnaissance:** through PR #474  

## Purpose

Prevent Study 1 from collapsing into a shallow comparison of time-to-next-fix, PR size, file count, or CI status. The study should explain **how change reasoning, semantic scope, architectural structure, proof, and corrective propagation interact**.

Fixed 7/14/30/60-day windows remain useful for right-censoring/sensitivity only. They do not define PR quality or architectural closure.

## Analytical levels

1. **Process/change level** — what was attempted; whether it merged, was revised, replaced, reverted, or abandoned.
2. **Semantic/system level** — contracts, states, authorities, boundaries, invariants and execution conditions implicated.
3. **Repair-mechanism level** — where the repair is applied and whether it reaches the authoritative control point.
4. **Proof/closure level** — whether the real failure mode is exercised and whether independent architecture evidence confirms closure.
5. **Network/outcome level** — whether the PR terminates, propagates, relocates, exposes, or branches later corrective work.
6. **Measurement-system level** — what graph/detector capabilities existed at the time and what defects they could observe.

## Variables to extract

### Change / defect mechanism

Adjudicate among:

- introduced defect;
- incomplete original change;
- regression;
- exposed latent defect;
- required hardening;
- planned extension;
- requirements change;
- architecture/instrumentation change;
- correction of a correction;
- revert;
- supersession/abandoned design;
- unrelated;
- uncertain.

Do not use `fix:`/`feat:` title prefixes as causal classifications.

### Semantic scope

Code at minimum:

- authority/permissions;
- identity/principal binding;
- state ownership;
- state transition/ordering;
- concurrency/single-use;
- idempotency;
- tenancy/RLS;
- persistence/transaction boundary;
- external side effects/egress;
- payload/contract semantics;
- runtime scheduling/leases;
- configuration/fail-fast;
- recovery/compensation;
- frontend/backend contract;
- proof obligation.

Semantic scope is not equivalent to file breadth.

### Architectural boundary coverage

Record:

- boundaries changed;
- boundaries depended on;
- graph-selected boundaries;
- boundary transitions explicitly proven;
- later corrective boundaries omitted from the original reasoning/proof.

This supports a direct reasoning-scope mismatch analysis.

### Invariant coverage

Record whether the PR:

- states the governing invariant;
- repairs a local symptom or a shared invariant cluster;
- changes violation/unknown state to enforced;
- proves the invariant at its real execution layer;
- preserves unrelated violations as visible negative evidence.

### Repair mechanism / control-point selection

Code whether the repair:

- patches individual callers;
- patches a shared service;
- introduces a new authority;
- reuses an existing durable authority;
- adds parallel coordination state;
- removes duplicated control paths;
- operates at the lowest/common authoritative point justified by the invariant.

### Proof topology

Separate proof layers rather than counting tests:

- unit;
- contract;
- integration;
- real database;
- real concurrency/contention;
- provider/runtime;
- fail-closed/adversarial;
- migration;
- graph semantic closure;
- negative-evidence preservation.

### Pre-merge interception

Capture:

- material defects discovered before merge;
- material design revisions;
- closed-unmerged attempts;
- explicit supersession/replacement;
- severity intercepted before `main`;
- final merged replacement.

A process that shifts defects from post-merge corrections into pre-merge redesign may improve production quality even if review findings increase.

### Corrective propagation topology

For every corrective PR, adjudicate whether it:

- terminates the chain;
- introduces another defect;
- leaves the governing invariant incomplete;
- relocates the problem across a boundary;
- exposes a latent defect;
- becomes parent of another corrective generation.

Measure depth, width, semantic fragmentation, boundary movement, severity movement, and repeated-file versus new-boundary correction.

### Graph maturity vector

Code capability actually available/used:

- static dependency visibility;
- transitive blast radius;
- impacted-test mapping;
- proof selection;
- semantic boundary modeling;
- invariant modeling;
- state/concurrency modeling;
- semantic finding generation;
- residual/negative-evidence ratchet;
- remediation closure reconciliation;
- architecture decision support.

Do not model graph treatment as only one before/after date.

## Candidate derived constructs

These remain provisional and must be construct-validated before inferential use:

- **Reasoning-Scope Coverage (RSC)**
- **Invariant Closure Ratio (ICR)**
- **Residual Visibility Rate (RVR)**
- **Repair Cluster Coherence (RCC)**
- **Proof Layer Coverage (PLC)**
- **Pre-Merge Interception Rate (PMI)**
- **Corrective Propagation Rate (CPR)**
- **Semantic Fragmentation Depth (SFD)**
- **Symptom-to-Invariant Compression (SIC)**
- **Architecture Adjudication Debt (AAD)**

No composite PR-quality score is authorized at this stage.

## Historical mechanisms motivating the framework

### #58 → #59 — semantic mismatch inside a tiny file surface

Both PRs change only a small surface, yet #59 explicitly corrects late feedback on #58. The relevant problem is the relationship between handler-result contract and dispatcher lifecycle semantics, not missing file reachability.

Graph+ implication: contract/state-machine semantics matter beyond import dependencies.

### #107 → #108 — temporal/state-ordering semantics

#108 explicitly reports that #107 checked lease state after mutating it to `EXPIRED`. A one-file path can still be architecturally wrong because required observation must precede transition.

Graph+ implication: model ordering/state-transition obligations, not only nodes/edges.

### #369 → #370 → #371 → #372 → #373 → #374 — progressive semantic discovery

The earlier working sample stopped at #372. Full-population reconnaissance found two additional direct corrective generations:

- #373: `Codex P2 on #372` — reserved `.example/.test/.local` placeholders must be rejected before external send;
- #374: `Codex P2 on #373` — exact-domain/single-label reserved-domain rejection before `gtm.email_send`.

The component therefore progresses through multiple semantic conditions of one outreach execution path: world-state production, binding, action payload semantics, execution eligibility, deliverable-recipient safety, reserved-domain safety, and exact-domain safety.

This is a priority case for testing **Semantic Fragmentation Depth**, not merely PR count.

## PR #460+ mechanisms

### #460 / #465 — stronger conventional repair discipline

These PRs show strong root-defect descriptions, broad contract/security reasoning, explicit non-goals and extensive proof, but closure is still primarily implementation/test-centric.

### #468 — measurement-system intervention

#468 expands graph visibility into RLS, egress and state/concurrency semantics and preserves baseline known violations. This can increase defect discovery without increasing defect creation; detector maturity must therefore be modeled independently.

### #469 — cross-boundary repair and real failure-mode proof

RLS migration and raw-session tenant activation are repaired together because either side alone is unsafe. Real PostgreSQL isolation proof and semantic graph closure are both required.

### #470 — architecture adjudication as versioned work

An intentional pre-tenant control-plane exception is made explicit while remaining GF-11 defects stay visible. Model defects and implementation defects must be distinguishable.

### #471 → #472 — pre-merge architectural supersession

A narrower/different Redis design does not enter `main`; a broader PostgreSQL durable execution authority from the same base does. Preserve this as process/interception evidence without claiming the graph caused the redesign absent direct evidence.

### #473 — shared-invariant compression

GF-14/GF-22/GF-23 are treated as one single-use successor-authority invariant and repaired through existing durable rows rather than three independent patches. This motivates **Repair Cluster Coherence** and **Symptom-to-Invariant Compression**.

## Graph maturity reconstruction

The contemporaneous sequence provides a capability timeline that can be coded without outcome selection:

- #453 — diff-aware invariant classifier;
- #454 — canonical dependency graph;
- #455 — graph-aware blast-radius analysis;
- #456 — graph-aware proof selection;
- #457 — selective-CI shadow execution;
- #458 — graph completeness audit;
- #459 — architecture decision manifest;
- #460 — provisional first graph-assisted production correction;
- #468 — semantic RLS/egress/state-concurrency hardening;
- #469+ — graph-integrated closure examples.

This sequence should be represented as a treatment-capability vector, while procedural architecture practices such as UPG/LAP and authority-ledger reasoning before graph maturity are retained as confounders/comparators.

## Research propositions to test, not assume

1. Semantic scope mismatch predicts cascades better than file breadth alone.
2. Deep corrective chains often represent progressive discovery of one governing invariant.
3. Graph assistance may improve repair quality by clustering symptoms around shared invariants and authoritative control points.
4. Failure-mode-aligned proof predicts closure better than raw test quantity.
5. Preserving unrelated known defects as visible evidence is a measurable quality property.
6. Pre-merge interception/supersession may be an important benefit independent of post-merge descendant count.
7. Detector maturity can create an exposure spike and must be separated from software-quality deterioration.
8. Graph capability may improve first-pass architectural completeness without making PRs smaller.

Negative or mixed evidence must be retained.

## Operational link to extraction

The active extraction artifacts are:

- `data/pr-census-schema-v0.1.md`
- `analysis/extract_pr_population.py`
- `data/pr-population-partition-manifest-v0.1.csv`
- `data/semantic-adjudication-queue-v0.1.csv`
- `analysis/extraction-method-v0.1.md`

All automated candidate relationships begin `unadjudicated`. Population-wide causal claims begin only after calibration and evidence-grade adjudication under the study protocol.
