# Full-Population Extraction Method v0.1

**Status:** working method; revisable  
**Snapshot boundary:** through Ajenda PR #474  
**Purpose:** convert the multivariate framework into a reproducible population-level dataset without allowing automated signals to masquerade as findings.

## 1. Population frame

The extraction target is the Ajenda pull-request history through PR #474. The repository PR collection, not GitHub search ranking, is the authoritative enumeration mechanism for the reproducible census.

A partitioned GitHub search was used as an independent reconnaissance/completeness check because a single search result set can silently cap at approximately 100 entries. The search partition manifest records those windows and identifies the early partitions that still require exact reconciliation against the repository collection.

The snapshot is frozen by **maximum PR number**, not by an ambiguous local/UTC date boundary.

## 2. Two-layer extraction design

### Layer 1 — deterministic census

Extract for every PR:

- state and merge status;
- timestamps;
- base/head/merge SHAs;
- commit/file/addition/deletion counts;
- author;
- title/body hash;
- conservative explicit prior-PR references;
- deterministic text/process signals;
- provisional population-routing label.

Layer 1 is reproducible from GitHub and may be regenerated.

### Layer 2 — semantic and causal adjudication

Do **not** infer the study variables merely from title labels or lexical signals. Adjudicate against PR body, diffs, tests, merge ancestry, review evidence, later corrective evidence, graph state, and relevant source history.

The seeded queue contains likely positive cases, ambiguous cases, supersessions/reverts, exposure cases, and planned progression cases. This is intentional so rubric calibration is not conditioned only on apparent cascades.

## 3. Population inclusion roles

Maintain at least three analytically distinct sets:

1. **Merged product-development population** — primary production-causality population.
2. **Closed-unmerged/replaced design attempts** — process/pre-merge interception evidence; not merged production causality.
3. **Research/instrumentation and unrelated dependency maintenance** — retained in raw census but excluded or separately modeled according to protocol.

Never discard excluded PRs from raw evidence. Exclusion is an analysis field, not data deletion.

## 4. Semantic extraction unit

File breadth is insufficient. For each adjudicated PR, code semantic dimensions such as:

- authority and permissions;
- identity binding;
- state ownership;
- transition/ordering;
- concurrency/single-use;
- idempotency;
- tenancy/RLS;
- persistence/transaction boundary;
- external-effect/egress;
- payload/contract semantics;
- scheduling/lease semantics;
- configuration/fail-fast;
- recovery/compensation;
- frontend/backend contract;
- proof obligation.

A PR may touch one file yet span multiple semantic dimensions, or many files while implementing one coherent invariant.

## 5. Causal-edge adjudication

For each candidate source→target relationship:

1. verify merge/order history;
2. inspect explicit references in target PR/review/test evidence;
3. determine whether source introduced, exposed, incompletely implemented, or merely preceded the target condition;
4. inspect source diff and affected contract history;
5. classify relationship under the frozen rubric;
6. assign evidence grade;
7. record uncertainty rather than force a class;
8. code semantic dimensions and boundary movement;
9. determine whether target itself later propagates the chain.

Chronology and file overlap alone are never sufficient.

## 6. Repair-cluster reconstruction

Do not analyze only PR pairs. After edge adjudication, assemble connected corrective components and reconstruct:

- originating change(s);
- corrective generations;
- width/branching;
- semantic dimensions discovered at each generation;
- severity movement;
- boundary movement;
- repeated-file versus newly implicated boundaries;
- termination, propagation, exposure, or supersession state.

This is required to detect progressive invariant discovery such as the outreach chain beginning at #369.

## 7. Pre-merge interception

A graph-assisted process may improve quality by stopping a weaker design before merge rather than by reducing all review findings. Therefore separately extract:

- closed-unmerged design attempts;
- explicit replacement/supersession;
- material review findings before merge;
- material design broadening before merge;
- severity intercepted before `main`;
- final merged replacement.

#471→#472 is a priority calibration case for this variable.

## 8. Graph maturity reconstruction

Do not encode treatment as only `pre/post #460`.

Reconstruct graph capabilities from contemporaneous PR evidence. The current candidate maturation sequence is:

- #453 — diff-aware invariant classifier;
- #454 — canonical dependency graph;
- #455 — graph-aware blast-radius analysis;
- #456 — graph-aware proof selection;
- #457 — selective-CI shadow execution;
- #458 — graph completeness audit;
- #459 — architecture decision manifest;
- #460 — provisional first graph-assisted production correction;
- #468 — semantic hardening for RLS, egress, state/concurrency and known-violation ratchet;
- #469 onward — graph-integrated remediation/closure examples.

Each PR should receive the capability vector actually available and, where evidence permits, actually used.

## 9. Measurement-system maturity as a confounder

Stronger graph instrumentation can increase detected defects without worsening software. Model separately:

- detector capability available;
- finding class newly observable;
- whether a later PR repairs a newly introduced defect or a newly observed latent defect;
- whether residual known defects remain visible after repair.

This avoids interpreting an exposure spike as treatment harm.

## 10. Time variables

Elapsed time remains useful but secondary.

Record continuous time-to-event and PR-distance variables. Fixed 7/14/30/60-day windows may be used later for sensitivity/right-censoring comparisons, but they do not define architectural closure or PR quality.

## 11. Quality assurance

Before inferential analysis:

- reconcile all PR numbers through the snapshot boundary against the repository collection;
- preserve extraction timestamp and raw body hashes;
- rerun extraction and diff generated outputs;
- hand-check a random sample of machine signals;
- calibrate 30–50 causal relationships, including negative/ambiguous controls;
- revise the rubric at most once under the protocol and record the amendment;
- freeze the adjudication rubric before population-wide causal classification;
- retain uncertain edges;
- keep research-only/excluded records in raw census.

## 12. Current reconnaissance observations requiring systematic testing

These are queue-generating observations, not final findings:

- small/same-file changes can propagate semantic corrections (#58→#59, #107→#108);
- the #369 corrective component extends beyond the previously documented #372 endpoint through #373 and #374;
- several periods contain explicit replacement/revert patterns, supporting pre-merge/supersession analysis;
- procedural architecture language (UPG/LAP, authority ledgers, proof obligations) appears before canonical graph maturity and is therefore an important confounder/comparator;
- #453–#459 provides a reconstructable graph-capability maturation sequence;
- #468 changes detector observability and must be modeled separately from product-remediation effects.

These observations justify the extraction dimensions; they do not establish treatment effect.
