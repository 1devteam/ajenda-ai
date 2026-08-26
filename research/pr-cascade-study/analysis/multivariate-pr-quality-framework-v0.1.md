# Multivariate PR Quality & Graph-Effect Analysis Framework v0.1

**Status:** exploratory analytical framework; not an empirical finding  
**Snapshot:** Ajenda history reviewed through PR #473  
**Purpose:** prevent the prospective analysis from collapsing into a shallow time-to-next-fix comparison

## Core correction

Fixed 7/14/30/60-day observation windows are useful for right-censoring and comparability, but they are **not the primary definition of PR quality, architectural closure, or graph effectiveness**.

Ajenda contains richer evidence at multiple levels:

1. **change/process level** — what the PR attempted, how it was packaged, revised, superseded, or merged;
2. **semantic/system level** — which contracts, states, authorities, boundaries, and invariants were actually implicated;
3. **proof/closure level** — whether the real failure mode was tested and whether architecture state was reconciled;
4. **network/outcome level** — whether the PR terminates, propagates, relocates, or exposes later corrective work.

The study should use time windows only as one censoring control within this broader model.

---

## 1. Variables that should be extracted from the PR population

### A. Defect / change mechanism

Code each PR or causal edge by mechanism, not merely `feat` / `fix` label:

- introduced defect;
- incomplete original change;
- regression;
- exposed latent defect;
- required hardening;
- planned extension;
- requirements change;
- architecture/instrumentation change;
- correction of a previous correction;
- superseded / abandoned design.

A central study outcome is **repair closure versus corrective propagation**, not simply whether another `fix:` PR appears.

### B. Semantic scope

Capture which semantic classes the change touches:

- authority / permissions;
- identity / principal binding;
- state ownership;
- state transitions / ordering;
- concurrency / single-use semantics;
- idempotency;
- tenancy / RLS;
- persistence / transaction boundary;
- external side effects / egress;
- contracts / payload shape;
- runtime scheduling / leases;
- configuration / fail-fast behavior;
- recovery / compensation;
- frontend/backend contract;
- proof obligation.

This is different from file count. A two-file PR can have a large semantic blast radius, while a 20-file migration ratchet can be semantically narrow.

### C. Architectural boundary crossing

For each PR, record:

- boundaries changed;
- boundaries depended on but not changed;
- boundaries selected by graph impact;
- boundary transitions explicitly tested;
- later corrective descendants that land in a boundary omitted from the original reasoning/proof.

This permits a direct **reasoning-scope mismatch** measure.

### D. Invariant coverage

Record whether the PR:

- names a system invariant;
- repairs one symptom or a cluster sharing an invariant;
- changes the invariant state from violated/unknown to enforced;
- proves the invariant at the correct execution level;
- preserves unrelated known violations rather than accidentally hiding them.

### E. Repair-cluster coherence

A PR addressing multiple defects can be either coherent or merely large.

Candidate measure:

**Repair Cluster Coherence (RCC)** = proportion of addressed findings that share one explicit governing invariant or authority mechanism.

Examples:

- GF-13/GF-25/GF-26/GF-27 plus GF-28 adjudication in #472 share HTTP operation-identity / durable execution-ownership semantics.
- GF-14/GF-22/GF-23 in #473 share atomic single-use successor-authority semantics.

This may be more informative than PR size.

### F. Repair mechanism centrality

Record whether a PR:

- patches individual callers;
- patches one shared service;
- introduces a new central authority;
- reuses an existing durable authority;
- adds parallel state/coordination mechanisms;
- eliminates duplicated control paths.

A graph-assisted repair may create value by identifying the **lowest common control point**, not just by finding more affected files.

### G. Proof topology

Do not count tests as interchangeable.

Record proof layers separately:

- unit;
- contract;
- integration;
- real database;
- real concurrency/contention;
- runtime/provider;
- fail-closed / adversarial;
- migration;
- graph semantic closure;
- negative-evidence preservation.

Candidate measure:

**Proof Layer Coverage (PLC)** = required failure-mode proof layers actually exercised / required layers identified.

Test-file count alone is not sufficient.

### H. Architectural closure observability

Record whether the post-change system provides independent evidence that:

- targeted finding(s) disappeared;
- invariant state changed as intended;
- unrelated known findings remained visible;
- architecture exceptions are explicit rather than silently omitted;
- observed implementation still matches the intended semantic model.

This is different from CI green.

### I. Pre-merge defect interception

Separate defects discovered and corrected **before merge** from corrective descendants after merge.

Candidate outcomes:

- review-discovered defect count;
- design supersession before merge;
- abandoned PR rate;
- issue severity intercepted before merge;
- number of material implementation revisions prior to merge;
- post-merge corrective descendants.

A stronger graph process could increase pre-merge findings while decreasing escaped defects. Counting only later PRs would miss that benefit.

### J. Residual-defect visibility

A repair process can appear clean by deleting or suppressing evidence.

Candidate measure:

**Residual Visibility Rate (RVR)** = unrelated known findings still represented after a targeted repair / unrelated known findings represented before it.

Graph+ should ideally approach 1.0 for unrelated defects: fixing A should not make B vanish from the evidence model unless B was genuinely changed.

### K. Corrective propagation topology

For each corrective PR, determine whether it:

- terminates the chain;
- introduces a new defect;
- leaves a connected invariant incomplete;
- relocates the problem to another boundary;
- exposes a latent defect;
- becomes the parent of another corrective generation.

Metrics:

- corrective propagation rate;
- repair closure rate;
- secondary correction depth;
- cascade width;
- boundary migration of the cascade;
- repeated-file versus new-boundary correction;
- severity escalation/de-escalation across generations.

### L. Graph maturity as a vector, not a date

Graph treatment should not be represented only as `before/after #460`.

Candidate graph-capability dimensions:

- static dependency visibility;
- transitive blast radius;
- test/proof selection;
- semantic boundary modeling;
- invariant modeling;
- state/concurrency modeling;
- semantic finding generation;
- negative-evidence ratchet;
- graph closure after remediation;
- architecture decision support.

A PR receives the graph capabilities actually available/used at that point.

---

## 2. Historical evidence viewed through these variables

### #58 → #59: file coverage was not the missing variable

#58 hardened handler output validation and explicitly allowed `completed`, `failed`, and `blocked`. #59 immediately restricted the result status back to `completed` and explicitly identifies late feedback from #58.

Both PRs changed only two files.

Interpretation:

- this is not a simple case of a huge file blast radius being missed;
- the failure was a **semantic mismatch between the output contract and dispatcher lifecycle semantics**;
- a file-dependency graph alone would not necessarily detect it;
- Graph+ needs contract/state-machine semantics such as `result.status -> permitted dispatcher transition`.

This is evidence that **semantic blast radius can exceed file blast radius even when the same files remain involved**.

### #107 → #108: dependency reachability is insufficient for temporal semantics

#107 added recovery mismatch diagnostics. #108 explicitly says #107 checked `lease.status` after transitioning the lease to `EXPIRED`, defeating the diagnostic.

Both are one-file changes.

Interpretation:

- no cross-module dependency omission is required to create the defect;
- the defect is **operation ordering / state-transition semantics inside one path**;
- Graph+ therefore needs temporal/state-transition rules, not only nodes and dependency edges.

Candidate semantic relation:

`observe(original_lease_state)` **must precede** `transition(EXPIRED)` when the invariant requires diagnosis of the prior state.

### #369 → #370 → #371 → #372: progressive semantic discovery

#369 changed 13 files across composition, runtime authority, action input binding, tools, schemas, projection, and worker runtime. The follow-up chain then progressively discovered:

1. #370 — effective side-effect authority, action-specific payload shape, richer-state merging, and real/simulated state semantics;
2. #371 — compiled `email_send` path could not satisfy its binding contract;
3. #372 — the repaired binding logic still allowed a placeholder recipient to unlock external send, requiring a fail-closed deliverability gate.

The file surface actually contracts during the cascade:

- #369: 13 files;
- #370: 5 files;
- #371: 2 files;
- #372: 2 files.

#371 and #372 both concentrate on `mission_input_binding.py` plus its unit test.

Interpretation:

This is not simply "a large PR caused more bugs." The sequence shows **successive discovery of different semantic dimensions of one outreach execution chain**:

`world-state production` → `binding` → `action contract` → `execution eligibility` → `external-effect safety`.

The later P1 exists even after the repair surface has collapsed to one production file. This strongly motivates invariant-centered graph reasoning.

Candidate Graph+ invariant:

> An external-send action may become executable only when bound world state contains a non-simulated, deliverable recipient and all required authority/data contracts are satisfied.

A graph that contains only imports would not encode that invariant.

---

## 3. PR #460 onward viewed through additional scopes

### #460 — improved boundary reasoning, but closure remained test-centric

#460 identified five authority/ownership defects spanning authentication path classification, platform-vs-tenant authority, human attribution, branch ownership, and workforce ownership.

Useful variables:

- **semantic breadth:** high;
- **boundary breadth:** auth middleware, RBAC/PDP/OPA, API routes, service ownership, audit attribution;
- **proof topology:** broad unit/contract regression coverage;
- **changed-file structure:** 14 production files + 13 tests;
- **graph closure:** absent;
- **residual visibility:** controlled textually through explicit non-goals rather than machine ratchet.

This is a strong corrective PR, but its definition of closure is still primarily implementation + regression proof.

### #465 — strong local contract repair with a broader invariant still open

#465 repaired password signup/email verification across API, service, delivery, token logic, frontend, and multiple integration suites.

Useful variables:

- **proof investment:** high; 8 implementation/frontend files and 16 test files changed;
- **security contract clarity:** high;
- **scope discipline:** high;
- **broader invariant closure:** incomplete, because GF-14 later shows verification consumption was still non-atomic under concurrency.

This does **not** mean #465 introduced GF-14. It means the behavioral/email-ownership repair and the concurrency/single-use invariant are different semantic dimensions.

This distinction should become a dataset field: **local contract closed / governing invariant still open**.

### #468 — change in observability, not product behavior

#468 is important because it increases what the graph can see:

- RLS/table semantics;
- egress lanes;
- state resources;
- concurrency/single-use/idempotency invariants;
- acknowledged baseline violations;
- fail-on-new-unacknowledged semantic findings.

This is a **measurement-system intervention** as much as a development intervention.

That creates a confounder and a benefit:

- more defects may be observed because the detector became stronger;
- better observability may prevent false claims of closure.

The study must model detector maturity separately from production quality.

### #469 — blast-radius closure includes migration + runtime activation

#469 explicitly identifies a failure mode that a local migration-only fix could create: enabling RLS without repairing raw session consumers could convert an isolation defect into an outage.

It therefore lands:

- RLS migration;
- tenant activation in quota middleware;
- tenant activation in webhook dispatch;
- real PostgreSQL cross-tenant/fail-closed proof;
- graph semantic closure.

Useful variables:

- **repair-cluster coherence:** high;
- **cross-boundary synchronization:** migration + middleware + tool runtime + graph;
- **proof level:** real database rather than only mocks;
- **negative evidence:** old GF-11 omissions remain explicitly open;
- **changed-file structure:** only 4 non-test implementation/instrumentation files but 17 test files.

This shows why file count alone is weak: a four-file implementation can encode a cross-boundary architectural repair if the correct control points are chosen.

### #470 — semantic certification as a distinct engineering activity

#470 changes no runtime behavior. It adjudicates `customer_auth_sessions` as an explicit pre-tenant/control-plane RLS exception and ratchets the graph so repaired findings stay gone while older GF-11 omissions remain visible.

This is important because it makes **architecture interpretation itself versioned and testable**.

Potential outcome variable:

**Architecture adjudication debt** — unresolved graph findings caused by incomplete semantics/modeling rather than unresolved application defects.

Graph+ quality depends on separating implementation defects from model defects.

### #471 → #472 — pre-merge design supersession

#471 and #472 share the same base SHA.

#471 proposed Redis-backed ownership for GF-13/GF-27 while explicitly deferring GF-25/GF-26/GF-28. It was closed unmerged.

#472 instead treats the broader HTTP idempotency cluster as one architecture problem and merges a PostgreSQL-backed durable authority covering:

- atomic claim-before-execution;
- operation identity / changed-payload conflict;
- transient-response policy;
- multi-worker durability;
- encrypted replay state;
- abandoned-claim recovery;
- graph closure.

The #472 commit sequence itself is also useful process evidence: durable model → atomic repository → authority → migration → middleware ownership → semantic tests → real PostgreSQL contention/recovery → graph-closure proof → graph model marked enforced.

Do not infer that the graph *caused* this sequence without contemporaneous task/review evidence. But code it as **pre-merge architectural broadening and design supersession**, not as post-merge corrective rework.

This is a crucial outcome class that time-to-next-PR misses entirely.

### #473 — shared-invariant repair with mechanism reuse

#473 groups GF-14/GF-22/GF-23 under one invariant:

> current credential authority must be atomically consumed before successor authority is minted.

Instead of adding a new coordinator, it identifies the existing durable rows as the ownership points and applies PostgreSQL row locking there.

Useful variables:

- **repair-cluster coherence:** very high;
- **mechanism reuse:** high;
- **new coordination surface:** low;
- **real concurrency proof:** present for all three transitions;
- **graph closure:** three targeted findings removed;
- **residual visibility:** GF-12/GF-16/GF-30, GF-11, GF-07/GF-08 remain visible.

This may indicate a graph-assisted benefit different from simple blast-radius expansion: **finding the common invariant and the smallest authoritative repair point across multiple symptoms**.

That should be tested explicitly.

---

## 4. Preliminary cross-scope observations worth testing

These are research propositions, not final findings.

### P1 — Semantic scope may matter more than file scope

Historical corrective cascades occur even when later fixes touch the same one or two files (#58/#59, #107/#108, #371/#372).

Therefore a model based only on changed-file count, dependency reach, or repository breadth is likely incomplete.

### P2 — Corrective cascades can represent progressive invariant discovery

The #369–#372 chain is consistent with progressively discovering different conditions of one execution invariant rather than unrelated defects.

If this pattern recurs across the census, **cascade depth may be interpretable as semantic fragmentation depth**.

Candidate measure:

**Semantic Fragmentation Depth (SFD)** = number of distinct semantic dimensions of the same governing invariant discovered in successive corrective generations.

### P3 — Graph value may come from defect clustering, not only blast-radius prediction

#472 and #473 organize multiple frozen findings around shared control invariants.

A possible Graph+ benefit is reducing repair fragmentation by converting many symptom-level findings into one coherent root-level repair package.

Candidate measure:

**Symptom-to-Invariant Compression (SIC)** = number of validated defect findings coherently closed per governing invariant / repair mechanism.

High SIC is not automatically good; the package must remain reviewable and independently proven.

### P4 — Proof quality is about failure-mode alignment, not test quantity

Changed-test-file share is not monotonic across the stronger PRs. #473 changes fewer test files than #469/#472 but includes direct PostgreSQL contention proof and graph closure.

The study should score **proof topology** rather than raw test count.

### P5 — Negative evidence preservation is itself a quality signal

#468+ makes it possible to prove not only what disappeared but what **must remain visible**.

That guards against accidental evidence erasure and overclaiming repair completion.

This is rare in ordinary PR-quality metrics and should be treated as a first-class Graph+ outcome.

### P6 — Pre-merge interception can substitute for post-merge corrective work

#471 is a clear process example: a proposed design existed, was not merged, and a broader design from the same baseline replaced it.

If stronger architecture reasoning shifts correction left, then post-merge cascade counts alone understate the effect.

We need both:

- **pre-merge correction/supersession**, and
- **post-merge corrective propagation**.

### P7 — Graph maturity may change the type of defect discovered

As semantic modeling expands, observed defect counts may rise because new classes become visible (RLS, egress, concurrency/state ownership).

A raw count of findings before vs after graph maturity could therefore reverse the true interpretation.

Measure:

- detector capability available;
- defect class detectable;
- whether finding was newly introduced or newly observable.

### P8 — Graph+ must model more than dependency reachability

Historical evidence requires at least:

- state transitions/order;
- authority and ownership;
- payload/contract semantics;
- concurrency/single-use rules;
- external-effect eligibility;
- fail-closed behavior;
- recovery/compensation;
- invariant satisfaction.

Otherwise Graph+ risks becoming a sophisticated file dependency map that still misses the causal mechanisms behind Ajenda's corrective cascades.

---

## 5. Candidate composite measures for the full census

These are provisional and must be calibrated before inferential use.

| Measure | Purpose |
|---|---|
| **Reasoning-Scope Coverage (RSC)** | How much of the eventual causal architectural surface was represented in the original reasoning/proof scope. |
| **Invariant Closure Ratio (ICR)** | Targeted invariant/finding claims actually closed with evidence divided by targeted claims. |
| **Residual Visibility Rate (RVR)** | Unrelated known findings retained after repair divided by unrelated known findings visible before repair. |
| **Repair Cluster Coherence (RCC)** | Share of findings in a repair package governed by one explicit invariant/control mechanism. |
| **Proof Layer Coverage (PLC)** | Required failure-mode proof layers exercised divided by layers required by the defect mechanism. |
| **Pre-Merge Interception Rate (PMIR)** | Material defects/design failures corrected or superseded before merge divided by all material defects discovered for the change. |
| **Corrective Propagation Rate (CPR)** | Corrective PRs that become causal antecedents of further corrective work divided by corrective PRs with sufficient follow-up evidence. |
| **Semantic Fragmentation Depth (SFD)** | Number of distinct semantic dimensions of one invariant discovered across corrective generations. |
| **Symptom-to-Invariant Compression (SIC)** | Validated symptom/finding count coherently resolved per root invariant/control mechanism. |
| **Architecture Adjudication Debt (AAD)** | Open graph discrepancies attributable to model/semantic classification debt rather than unresolved implementation defects. |

Do not combine these into one quality score until reliability, scale behavior, and construct validity are tested.

---

## 6. Role of elapsed-time windows

7/14/30/60-day windows remain useful for:

- equalizing observation opportunity;
- right-censoring;
- calculating time to observed correction;
- sensitivity analysis.

They should **not** be the pillar of truth.

A PR can provide strong evidence immediately through:

- architecture closure;
- real failure-mode proof;
- preserved negative evidence;
- intercepted pre-merge defects;
- design supersession;
- reduced semantic fragmentation;
- correct invariant clustering.

Conversely, absence of a corrective PR for 30 days does not prove quality if the code was unused, the defect remained latent, or the detector could not observe that class.

---

## 7. Dataset expansion required

For the full Ajenda PR census, add fields beyond the existing causal-edge model:

### Change/process
- PR number / merge SHA;
- merged / closed-unmerged / superseded;
- requested objective;
- defect/change mechanism;
- original stated scope;
- explicit non-goals;
- review-discovered revisions;
- material pre-merge redesign;
- elapsed review/merge time.

### Semantic architecture
- semantic domains touched;
- graph maturity/capabilities available;
- graph nodes/edges selected;
- boundaries crossed;
- invariant(s) affected;
- state/authority/control point;
- predicted blast radius;
- actual implementation surface;
- eventual corrective surface.

### Proof
- proof layers used;
- graph-selected proofs;
- real vs mocked infrastructure;
- adversarial/fail-closed proof;
- graph findings before/after;
- targeted findings closed;
- unrelated findings retained;
- architecture adjudications/exemptions.

### Outcome
- pre-merge defects intercepted;
- post-merge corrective descendants;
- descendant causal class;
- cascade depth/width;
- semantic fragmentation dimensions;
- severity movement;
- time to correction/closure;
- whether descendant remained in same file/component or crossed a boundary;
- latent-defect exposure versus introduced/incomplete change.

---

## 8. Scientific caution

This framework expands what we measure; it does not establish that graph assistance improved Ajenda.

Potential alternative explanations remain:

- better prompts/instructions;
- stronger Codex/model capability;
- more mature developer review practice;
- increasing test maturity;
- security/remediation work naturally using stronger proof;
- later defects being selected from a frozen audit and therefore more explicitly specified;
- changes in architecture complexity over time;
- detector maturity increasing apparent defect discovery.

The research task is to determine which variables actually move together and which best predict closure/propagation.

The goal is not to prove "graph-first works." The goal is to identify **what graph capabilities, reasoning patterns, and repair structures—if any—are associated with better system-level closure** and which parts of the historical PR-cascade problem they address.
