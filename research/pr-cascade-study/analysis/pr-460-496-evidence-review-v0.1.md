# PR #460–#496 Evidence Review v0.1

**Status:** exploratory evidence review; not a findings document  
**Frozen repository boundary:** `1devteam/ajenda-ai` `main` at `9a3a3009217d0ea564bd0a04086330a5bc491db5` (merge of PR #496)  
**Observation date:** 2026-08-30  
**Study:** 1DevTeam PR Cascade Study  
**Research population:** Ajenda production-development history only; research-instrumentation PRs are excluded from product-quality outcome calculations  
**Cross-repository contamination rule:** `1devteam-web` is outside this evidence review. Website PRs, including 1devteam-web PR #16, are not Ajenda PR-cascade observations.

## 1. Purpose

This document preserves a detailed, source-bounded review of Ajenda PRs #460 through #496 and the graph/control capabilities immediately preceding them. Its purpose is to maximize retained information before later adjudication while avoiding a directional conclusion about whether graph-assisted development improved, degraded, or had no effect on PR quality.

The document is intentionally more descriptive than inferential. It records:

- the stated problem or purpose of each PR;
- whether the PR is product work, graph/measurement work, research instrumentation, dependency maintenance, or a closed-unmerged design;
- explicit root-defect statements where present;
- explicit invariants, policy boundaries, and ownership decisions where present;
- proof topology described by the PR;
- graph use or graph-state accounting described by the PR;
- explicit non-goals and residual-risk preservation;
- planned next slices versus later corrective follow-ups;
- pre-merge supersession candidates;
- plausible confounders and alternative explanations.

It does **not** assign a treatment effect. It does **not** treat PR prose quality as software quality. It does **not** infer causation from PR number adjacency.

## 2. Governing study rules

This review follows the current `research-protocol.md`, `definitions.md`, and `methodology.md` on `main`.

The following rules are especially important for this cohort:

1. A later PR is not a corrective descendant merely because it follows an earlier PR or touches related files.
2. Planned dependency work and feature evolution must be distinguished from rework caused by an incomplete or incorrect prior change.
3. A later discovery of a latent defect is not evidence that an earlier PR introduced that defect.
4. Closed-unmerged designs are retained as process evidence; they are not production defects because they did not enter `main`.
5. Detector or measurement improvement may increase the number of visible defects without increasing underlying software defect density.
6. Graph maturity is time-varying. The cohort cannot be modeled responsibly as a simple binary `graph off` / `graph on` switch.
7. PR size, prose length, number of tests listed, and CI success are not standalone quality measures.
8. Negative, mixed, and null evidence must be retained.

## 3. Source provenance and historical-method note

The current `main` branch contains the study protocol, definitions, hypotheses, methodology, and provenance notes, but the analysis/data files introduced by PR #474 are no longer present in the current `analysis/` and `data/` directories.

For this review, historical PR #474 material at commit `cb3871f9306ef733a7ca7798a0e737a35d9acaf5` was read as historical methodology input, not silently reinstated as current authority. Particularly useful historical concepts include:

- multivariate PR-quality assessment rather than a single score;
- graph capability represented as a maturity vector;
- separation of measurement-system maturity from product-quality change;
- semantic fragmentation depth;
- pre-merge interception/design supersession;
- residual-defect visibility;
- source-backed causal-edge adjudication.

Where this review uses those concepts, it treats them as analytical scaffolding consistent with the still-current protocol, not as final study findings.

## 4. Intervention-boundary caution

PR #460 remains a **provisional** production-comparison boundary because the graph/control stack was already being built before #460:

- #453 — diff-aware PR invariant classifier;
- #454 — canonical dependency graph foundation;
- #455 — graph-aware blast-radius analysis;
- #456 — graph-aware proof selection;
- #457 — selective-CI shadow execution;
- #458 — graph completeness audit;
- #459 — PR-facing graph architecture decision manifest.

Therefore, #460 should not be described as the origin of graph-assisted work. A more defensible model is a time-varying capability trajectory, with additional semantic/diagnostic maturation at #468 and #481 and proof-environment maturation at #492.

## 5. Graph/control capability trajectory relevant to the cohort

### 5.1 PR #453 — invariant classifier

Repository-observable purpose: convert existing architectural/authority doctrine into a diff-aware PR gate. The PR body states that changed files are classified into risk domains including tenant isolation, runtime authority, credentials, egress, persistence, frontend contracts, configuration, and action contracts. It also models the earlier Google Docs connector failure class as a case where route wiring, authority coverage, provider-route proof, and runtime credential-resolution wiring must move together.

**Study relevance:** graph-related reasoning begins as invariant/risk classification before the canonical graph itself. This is a confounder for any binary treatment definition based solely on #454 or #460.

### 5.2 PR #454 — canonical dependency graph

Repository-observable purpose: create a reproducible graph combining generated source relationships, test-to-production impact links, and an explicit semantic overlay for runtime authority, tenancy/RLS, credentials, network egress, external systems, frontend/backend contracts, configuration, and architectural invariants.

The PR reported a generated graph of 974 nodes and 3,130 typed edges at that revision.

**Study relevance:** the artifact is already broader than a file-import dependency map because the overlay encodes semantic and authority relationships. Later analysis should distinguish generated dependency evidence from semantic-overlay evidence rather than treating “the graph” as one undifferentiated mechanism.

### 5.3 PR #455 — blast-radius analysis

Repository-observable purpose: map changed repository paths to graph nodes and traverse upstream consumers, downstream prerequisites, impacted tests, semantic nodes, invariants, risk domains, and unmapped paths.

**Study relevance:** introduces a machine-readable predicted-impact surface. A later hypothesis can compare predicted/considered scope with realized corrective descendants, but that comparison requires archived per-PR graph outputs rather than PR-body language alone.

### 5.4 PR #456 — proof selection

Repository-observable purpose: convert graph impact into required proof bundles, tests, CI categories, and manual-review obligations.

**Study relevance:** graph influence may appear not only in code scope but in proof selection. A quality evaluation that measures only changed files would miss this mechanism.

### 5.5 PR #457 — selective proof in shadow mode

Repository-observable purpose: execute graph-selected focused proof while keeping full CI authoritative.

**Study relevance:** this is a measurement/safety phase, not evidence that selective graph proof was trusted as merge authority. The full suite remaining authoritative is an important control.

### 5.6 PR #458 — completeness/architecture audit

Repository-observable purpose: add centrality, consumer/dependency counts, boundary classification, SCC classification, semantic/static reconciliation, and fail-closed evidence integrity.

**Study relevance:** expands the graph from traversal into an architecture-model audit. It also explicitly allows `semantic-only` relationships without automatically calling them violations, which matters for avoiding overclaiming.

### 5.7 PR #459 — architecture decision manifest

Repository-observable purpose: consolidate graph impact, proof selection, and completeness into `clear`, `review-required`, or `blocked`, while explicitly stating that `clear` is not merge authorization and full CI remains required.

**Study relevance:** creates a PR-facing graph decision product before the #460 production correction.

### 5.8 PR #468 — semantic enforcement hardening

Repository-observable purpose: expand the graph’s semantic detection of database/RLS state, production egress, and state-ownership/concurrency invariants; preserve known baseline defects as acknowledged findings; fail on new unacknowledged blocking findings.

The body explicitly says this PR changes graph instrumentation and does not repair the application defects represented by those findings.

**Study relevance:** this is a major **measurement-system intervention**. An increase in visible defects after #468 cannot automatically be interpreted as worse code. Conversely, closing newly visible findings after #468 cannot automatically be credited as treatment success without accounting for detector availability.

### 5.9 PR #481 — function-level mission-composition diagnostics

Repository-observable purpose: add selective function-level nodes/call edges/test edges for mission composition so failures can be localized to decision functions such as segmentation, materiality classification, and interpretation rather than only to a module.

**Study relevance:** graph diagnostic granularity changes inside the cohort. Mission-composition work after #481 has a different diagnostic instrument than earlier #460 work.

### 5.10 PR #492 — pre-merge live runtime proof

Repository-observable purpose: run the prod-like Compose runtime proof on PRs before merge instead of only after push to `main`.

**Study relevance:** this changes the defect-interception environment independently of graph reasoning. Any apparent reduction in post-merge runtime corrections after #492 may be partly attributable to stronger pre-merge runtime proof.

## 6. Cohort partition: PR #460–#496

This partition is descriptive and may be revised after full causal adjudication.

| PR | Primary observed class | Product-quality population treatment | Important note |
|---|---|---|---|
| 460 | production corrective | include | authority/tenancy correction after graph-control stack |
| 461 | Dependabot CI dependency maintenance | exclude from product-quality comparison | closed unmerged |
| 462 | Dependabot frontend dependency maintenance | exclude | closed unmerged |
| 463 | Dependabot frontend dependency maintenance | exclude | closed unmerged |
| 464 | Dependabot frontend dependency maintenance | exclude | maintenance class; lifecycle should remain separately recorded |
| 465 | production corrective | include | password-signup ownership verification |
| 466 | research instrumentation | exclude | study bootstrap |
| 467 | prospective graph-guided correction/pilot | exclude from treatment-effect estimation | protocol/execution-history exception retained as process evidence |
| 468 | graph measurement-system intervention | analyze separately | semantic detector hardening |
| 469 | production corrective | include | graph-exposed RLS/session cluster |
| 470 | architecture adjudication/baseline certification | analyze separately | no runtime behavior change |
| 471 | closed-unmerged corrective design | pre-merge process evidence | idempotency design did not enter main |
| 472 | production corrective | include | durable HTTP execution ownership cluster |
| 473 | production corrective | include | three credential transitions under shared invariant |
| 474 | research instrumentation | exclude | historical full-population extraction work |
| 475 | production corrective | include | Redis lease owner integrity |
| 476 | production corrective | include | SMTP send ownership |
| 477 | production corrective | include | atomic API-key capacity ownership |
| 478 | production corrective | include | API-call metering semantics |
| 479 | closed-unmerged planned product design | pre-merge process evidence | superseded by #480 |
| 480 | product/commercial contract change | include as feature/config evolution, not corrective by default | pricing-capacity redesign after metering repair |
| 481 | graph capability intervention | analyze separately | function-level diagnostics |
| 482 | closed-unmerged corrective design | pre-merge process evidence | clause segmentation |
| 483 | production corrective | include | replacement/superseding clause segmentation fix |
| 484 | planned feature/semantic layer | include as feature evolution | typed deliverable request contract |
| 485 | planned feature/semantic wiring | include as feature evolution | explicitly announced by #484 |
| 486 | planned feature/semantic reconciliation | include as feature evolution | explicitly announced follow-up boundary |
| 487 | planned feature/semantic projection | include as feature evolution | candidate/bound/unresolved artifact mapping |
| 488 | planned feature/schema layer | include as feature evolution | typed artifact-field schemas |
| 489 | planned feature/completion evaluator | include as feature evolution | task completion separated from deliverable completion |
| 490 | planned runtime-state contract | include as feature evolution | durable non-authoritative deliverable state |
| 491 | planned runtime integration | include as feature evolution | worker completion/read-model wiring |
| 492 | CI/proof environment | analyze separately | pre-merge live runtime proof |
| 493 | observability feature | include as feature evolution | tenant-scoped deliverable runtime state read API |
| 494 | RevOps artifact schema expansion | include as feature evolution | explicit missing/unproven fields remain incomplete |
| 495 | runtime contract enforcement | include; may also be hardening | declared output contract enforced at worker completion |
| 496 | mission-level deliverable assembly | include as feature evolution | read-only assembler, completion independent from task success |

## 7. Detailed observations: early production corrections

### 7.1 PR #460 — platform and tenant mutation authority

The PR body enumerates five root defects rather than presenting one symptom. They span authentication-public path classification, platform-global recovery authority, human initiator attribution, branch RBAC/tenant ownership, and workforce RBAC/tenant ownership.

Observable engineering characteristics:

- explicit separation of tenant-header exemption from authentication-public status;
- introduction of `platform:operate` rather than reusing tenant runtime permission;
- explicit human-versus-machine authority distinction;
- ownership checks placed before persistence/quota use and again in deeper services for defense in depth;
- regression proof listed for positive and negative authority paths;
- a substantial explicit non-goal list.

Caution: this body does not itself prove the graph caused the broad scope. The appropriate coding is that #460 occurred after the #453–459 graph/control stack and exhibits broad authority/ownership reasoning. Causal attribution requires contemporaneous graph outputs or development records.

### 7.2 PR #465 — password-signup ownership verification

The PR body enumerates four root defects: immediate activation without ownership proof, magic-link/token UX mismatch, O(N) Argon2 public scan, and account-state enumeration.

Observable characteristics:

- changes span domain state, credential format/storage, public lookup complexity, delivery UX, frontend flow, and privacy behavior;
- the verification path is narrowed to indexed `email + code` followed by one Argon2 verification;
- compatibility behavior is explicitly constrained to non-production exposure mode;
- regression proof includes pending state, response privacy, code shape, valid/invalid/expired paths, and integration helper behavior;
- a broad non-goal list explicitly leaves concurrency/idempotency and other architecture areas unresolved.

Important later relation: PR #473 addresses a concurrency/single-use property involving verification tokens. That later finding must not be coded as introduced by #465 without source-history proof. A defensible provisional interpretation is that #465 strongly repairs the ownership-verification behavior while a broader concurrency invariant remains separately open.

## 8. Measurement intervention and graph-integrated remediation

### 8.1 PR #468 — detector hardening, not repair closure

#468 is analytically important because it makes previously implicit or incompletely modeled semantic risks first-class graph findings. It introduces acknowledged known-violation state for RLS, egress, and ownership/concurrency problems.

This changes what can be observed. Later repairs #469 and #472–#477 should be analyzed partly as responses to a newly strengthened measurement model. Their existence alone cannot establish that defects became more or less frequent.

### 8.2 PR #469 — RLS/session boundary repair

The PR states a cross-boundary pitfall explicitly: adding RLS policies without repairing raw `session_factory()` consumers would convert an isolation defect into a production outage.

Observable characteristics:

- migration and runtime session activation land atomically;
- three tenant-owned tables receive ENABLE/FORCE RLS, tenant policy, and admin bypass;
- middleware/action call paths are repaired to activate tenant context before SQL;
- proof includes unit ordering plus real PostgreSQL cross-tenant visibility/write failure/unset-context checks;
- graph semantic proof requires repaired findings to disappear;
- older frozen RLS omissions remain explicitly non-goals.

This is a strong example of implementation scope being framed around the architectural failure path rather than only the migration file. Whether the graph caused that scope remains a separate causal question.

### 8.3 PR #470 — baseline adjudication

#470 does not change runtime behavior. It classifies `customer_auth_sessions` as an explicit pre-tenant authentication/control-plane RLS exception and removes stale nonblocking entries for tables repaired by #469.

Study significance:

- demonstrates that graph closure includes adjudicating legitimate exceptions rather than forcing all visible relationships into a violation state;
- preserves remaining frozen findings;
- should not be counted as a product defect correction.

## 9. Pre-merge interception candidate: #471 → #472

### #471

Closed unmerged. Proposed a durable idempotency ownership primitive using Redis as shared production authority and intentionally left GF-25/GF-26/GF-28 for later semantic work.

### #472

Merged. Uses PostgreSQL-backed claim-before-execution and addresses the broader GF-13/GF-25/GF-26/GF-27 cluster, with GF-28 adjudicated as operation identity. It adds owner tokens, renewable leases, encrypted replay, response-cache policy, real 8-way PostgreSQL contention proof, and targeted graph closure.

**Working classification:** pre-merge architectural broadening/design supersession.

**What is observable:** #471 did not enter main; #472 did; they share the same general problem domain and #472 is broader in stated semantics and proof.

**What is not yet established:** why the design changed and whether graph evidence was the cause. Do not convert this into graph-benefit evidence without contemporaneous causal records.

## 10. Shared-invariant and ownership-oriented corrective sequence

### 10.1 PR #473 — single-use credential transitions

The PR groups three frozen findings under one invariant: current credential authority must be atomically consumed before successor authority is minted.

It reuses existing PostgreSQL authority rows and route transactions rather than introducing separate coordinators. Proof uses independent real PostgreSQL sessions with concurrent contenders for verification, bootstrap promotion, and refresh rotation.

The graph accounting expects three target findings to disappear while Redis lease, SMTP claim, API-key quota, RLS, and egress findings remain.

Study-relevant signature: one governing invariant spans multiple superficially different credential flows.

### 10.2 PR #475 — Redis lease owner integrity

The PR scopes one frozen finding and implements owner checks inside atomic Redis Lua transitions. It explicitly enumerates claim, heartbeat, complete, fail, release, recovery, and dead-letter ownership semantics.

Proof uses real Redis/Testcontainers and adversarial foreign-owner cases.

Graph accounting removes one finding while preserving SMTP/quota and other findings.

### 10.3 PR #476 — SMTP send ownership

The PR centers an asymmetric safety property: before the send fence, abandoned ownership can be recovered; after the send fence, ambiguous outcome must fail closed to prevent duplicate external delivery.

The design acknowledges SMTP’s lack of provider-side idempotency and accepts manual reconciliation over unsafe resend.

Graph accounting removes only the SMTP ownership finding and preserves unrelated findings.

### 10.4 PR #477 — API-key capacity ownership

The PR identifies `count active -> quota check -> create` as a concurrency race and chooses the tenant row as the per-tenant PostgreSQL reservation lock. Direct API-key creation and onboarding bootstrap issuance share the same authority.

Real PostgreSQL proof exercises two concurrent creators competing for the final slot.

Again, graph accounting removes one targeted finding while preserving unrelated ones.

### 10.5 Candidate pattern, not finding

Across #473, #475, #476, and #477, the PR bodies repeatedly organize corrections around:

`state resource -> governing invariant -> authoritative owner/serialization point -> adversarial concurrency proof -> targeted graph-state movement -> preservation of unrelated findings`.

This is an observable **documentation and repair-framing signature**. Whether it corresponds to lower downstream corrective propagation must be tested separately.

## 11. PR #478 and #480: policy semantics and planned commercial evolution

### #478 — API-call metering semantics

The PR separates monthly API-call quota from generic tenant-authenticated traffic. It makes trusted principal classification authoritative and uses the same classification for admission and post-success recording.

The body lists positive and negative policy cases and explicitly leaves pricing redesign out of scope.

### #479 / #480 — pricing capacity redesign

#479 is closed unmerged; #480 supersedes it. #480 states that #479 was replaced to force GitHub Actions certification onto the final immutable head after synchronize-event coalescing.

This is an important control: not every closed-unmerged/replaced PR indicates architectural correction. The stated reason here is certification mechanics. Pre-merge supersession must therefore be subclassified by cause.

#480 is also a planned downstream step after #478: metering semantics are repaired first, capacity values are redesigned second. This is planned product evolution unless later evidence proves rework.

## 12. Mission-composition diagnostics and clause correction: #481–#483

### #481

Adds function-level graph diagnostics specifically for mission composition without making the entire repository function-level. The body explains that a `clause_coverage` failure previously narrowed ownership only to `intent_interpreter.py`; the new layer distinguishes segmentation, materiality, and recognition decisions.

### #482

Closed-unmerged draft for clause segmentation. Keeps `clause_coverage` strict while changing segmentation around comma/semicolon/`and` boundaries and adding regression proof for the live SaaS mission.

### #483

Merged replacement of the clause-segmentation correction. It preserves descriptive conjunctions while continuing to isolate unsupported external-effect clauses and keep `clause_coverage` strict.

Working classification: #482→#483 is a pre-merge replacement in a graph-enhanced diagnostic environment. The reason for replacement needs source-backed adjudication before it is called defect interception or graph-driven broadening.

## 13. The #484–#496 sequence must not be mistaken for a corrective cascade

The long RevOps/deliverable sequence is a key methodological test. Sequential PR numbers and common subsystem membership are insufficient to label a cascade.

### 13.1 #484 — typed deliverable request contract

The PR establishes a separate typed composition-time vocabulary for requested report fields and explicitly lists next steps: wire into `MissionIntent` and clause coverage only after the contract is certified.

### 13.2 #485 — MissionIntent wiring

The PR wires the contract into canonical intent while deliberately **not** accounting detailed deliverable clauses yet. It explicitly announces that reconciliation as the next slice.

### 13.3 #486 — deliverable-clause accounting

The PR adds coverage reconciliation immediately before interpretation readiness while keeping unresolved fields fail closed.

### 13.4 #487 — artifact projection contract

Adds `bound`, `candidate`, and `unresolved` field states. Candidate bindings are explicitly not satisfaction. The PR announces typed schemas as the next slice.

### 13.5 #488 — typed artifact field schemas

Upgrades only subfields structurally guaranteed by known producer behavior and keeps other fields candidate/unresolved. It announces materialized-artifact validation as the next slice.

### 13.6 #489 — artifact-backed deliverable completion

Adds a pure evaluator and establishes the invariant that task/job completion can coexist with incomplete requested deliverables. It announces runtime wiring as the next slice.

### 13.7 #490 — durable deliverable runtime state

Adds persistable non-authoritative semantic state and says runtime should not reinterpret raw instruction at completion time. It announces mission-confirm persistence and runtime consumption as the next integration step.

### 13.8 #491 — runtime read-model wiring

The body is explicitly a staged integration plan: persist canonical state, refresh from worker completion using all mission siblings, preserve task/deliverable independence, and require live runtime proof.

### 13.9 #492 — pre-merge runtime proof

CI policy change to move prod-like proof before merge. This is proof-environment evolution, not a RevOps semantic correction.

### 13.10 #493 — runtime observability

Read-only tenant-scoped exposure of deliverable runtime state. It recomputes `complete` rather than trusting persisted summary state and returns conflict on forged/drifted data.

### 13.11 #494 — broader RevOps artifact schemas

Adds typed schema coverage for prospect/research/qualification fields while explicitly emitting missing producer values as empty rather than inventing claims. Empty structure does not satisfy completion.

### 13.12 #495 — worker-time output contract enforcement

Moves enforcement to `WorkerRuntimeService.complete()` so a task cannot complete merely because a handler returned some output; it must emit the exact server-declared artifact, and typed artifacts must satisfy structural schema.

The PR traces compiler, projection, runtime authority, dispatcher compensation, worker completion, deliverable completion, queue/lease state, and tests. It also explicitly distinguishes a structurally valid empty typed artifact from proof of deliverable completion.

### 13.13 #496 — mission-level deliverable assembly

Adds read-only assembly from completed declared artifacts plus current reviews, evidence, outcome reviews, and persisted side-effect outputs. It recomputes artifact completeness independently from task success and fails closed on tenant mismatch, invalid artifacts, request/projection drift, unresolved drafts, conflicting prospect fields, and missing real-effect receipt identifiers.

### 13.14 Working classification of the sequence

The bodies repeatedly predeclare the next architectural boundary. That is evidence for **planned staged construction** across much of #484–#496.

This does not mean the sequence is defect-free. It means the study must inspect later runtime evidence and pairwise source history before labeling any link as corrective rework.

A useful adjudication question for each pair is:

> Was the child PR implementing a boundary the parent explicitly deferred, or correcting a behavior the parent claimed was already complete/correct?

Only the latter is a strong corrective-cascade candidate absent other evidence.

## 14. Observable shifts in PR style and engineering presentation

The #460–#496 cohort increasingly uses recurring sections such as:

- Purpose / Problem / Defect;
- UPG/LAP or responsibility/source-of-truth/dependency analysis;
- Architecture / Policy / Invariants;
- Proof / Exact-head certification;
- Graph accounting;
- Scope boundary / Non-goals;
- Follow-up / next slice.

This is an observable **documentation-style shift**.

It is not by itself evidence of higher software quality. Possible explanations include:

- improved engineering reasoning;
- improved PR templates;
- different LLM prompting or model behavior;
- increased project maturity;
- security-remediation work naturally encouraging explicit invariants;
- graph tooling making certain concepts easier to express;
- later PRs being written after the study had already begun;
- stronger CI/checklist culture independent of graph causation.

The study should therefore score underlying evidence presence separately from prose structure.

## 15. Observable shifts in proof topology

Several later corrective PRs explicitly require proof at the mechanism’s real execution layer:

- PostgreSQL contention for single-use credentials and quota ownership;
- Redis/Testcontainers owner integrity;
- real PostgreSQL idempotency contention/replay;
- real PostgreSQL RLS isolation;
- prod-like Compose live runtime proof;
- graph semantic closure/ratchet tests;
- exact-head certification across multiple workflows.

This appears different from PRs that list only focused unit tests, but the baseline also contains integration tests and disciplined validation. Therefore the study should measure proof topology rather than use a simple “has tests” indicator.

Recommended proof codes:

- unit/static;
- contract;
- integration with real dependency;
- concurrency/contention;
- live/prod-like runtime;
- graph semantic closure;
- negative/adversarial proof;
- exact-head multi-gate certification.

## 16. Residual-defect visibility as a distinct variable

A notable later-cohort behavior is explicit preservation of unrelated known findings. Examples include #469 and #472–#477, where target findings are expected to disappear while named unrelated RLS/egress/ownership findings remain.

This should be measured separately from closure quality because it can indicate:

- honest scope control;
- improved measurement visibility;
- deliberate avoidance of overclaiming;
- or merely a PR-template convention.

It should not automatically increase a quality score.

## 17. Pre-merge interception needs cause-specific coding

Candidate cases in this cohort demonstrate why `closed_unmerged` cannot be treated uniformly:

- #471→#472: plausible architecture/design supersession; causal mechanism not yet adjudicated;
- #479→#480: PR body explicitly attributes replacement to CI certification binding, not design correction;
- #482→#483: replacement around clause-segmentation work; causal reason still needs source-backed adjudication;
- #467: process/protocol exception; excluded from treatment-effect estimation.

Recommended subclassification:

- `design_broadened_premerge`;
- `review_defect_intercepted_premerge`;
- `ci_or_branch_mechanics_replacement`;
- `protocol_execution_exception`;
- `unknown`.

## 18. Confounders and rival explanations that must remain active

### 18.1 Developer/model learning over time

Later PRs may improve because the developer/LLM learned the architecture, independent of graph tooling.

### 18.2 CI maturation

#492 materially changes pre-merge runtime proof. Other CI/security/recovery workflows also mature. Reduced post-merge defect escape could come from stronger gates.

### 18.3 Test-suite accumulation

Later work benefits from more existing regression tests and utilities. Better proof selection may be partly enabled by a richer test base.

### 18.4 Work-type composition

The #472–#477 sequence is largely frozen security/concurrency remediation. Such work naturally invites invariant-centric framing and adversarial proof. Comparing it directly with feature work can confound task class with graph effect.

### 18.5 Measurement-system maturity

#468 and #481 increase defect visibility and localization. More discovered defects may reflect better measurement, not worse software.

### 18.6 PR template/prose evolution

Later bodies are substantially more structured. Documentation quality can change independently of implementation completeness.

### 18.7 Review process/model changes

Historical PRs explicitly mention Codex feedback. Any change in review model, model version, prompt, or review timing can affect corrective propagation.

### 18.8 Selection bias in comparator cases

The dramatic #369–#374 chain is useful but cannot stand in for all pre-450 development. The baseline must include both cascading and non-cascading work.

### 18.9 Time-at-risk / right censoring

PRs near #496 have had far less downstream observation time than older PRs. Corrective-descendant rates must use censoring controls rather than raw counts.

## 19. Evidence that would argue against a graph benefit

The study must actively retain observations such as:

- post-graph production PRs that generate multi-generation corrective descendants;
- graph-selected scope that omits a later-affected boundary;
- graph evidence that is wrong, stale, or too coarse to influence the repair;
- graph use that adds process cost without changing implementation/proof decisions;
- defects repeatedly found only by external review/runtime after graph certification;
- closed-unmerged graph-guided designs that are replaced because the graph recommendation was inadequate;
- runtime failures where a local code-first repair proves complete and graph inspection adds no material information.

These are not “failures of the study”; they are necessary falsifying evidence.

## 20. Evidence that would support a graph contribution without proving causality

Potential contribution signals include:

- graph inspection identifies an affected boundary not present in the pre-graph diagnosis;
- graph evidence groups superficially separate symptoms under one invariant or owner;
- predicted blast radius leads to code/test changes outside the initially suspected module;
- graph-selected proof catches a defect before merge;
- graph semantic closure prevents overclaiming by preserving unrelated findings;
- function-level diagnostics change the root-cause hypothesis;
- repair descendants decrease in semantic fragmentation depth after controlling for work type, detector maturity, and time-at-risk.

Each requires source-backed evidence; none should be inferred from PR language alone.

## 21. Current neutral synthesis

The repository supports the following **descriptive** statements at this snapshot:

1. Ajenda’s graph/control capability matured substantially before and during PR #460–#496.
2. Later corrective PR bodies, especially after #468, more often make invariants, ownership, residual findings, and proof topology explicit.
3. Several later security/concurrency repairs are framed around one authoritative state owner and use real contention/integration proof.
4. Several closed-unmerged PRs show that pre-merge replacement exists, but the reasons differ and must be subclassified.
5. The #484–#496 RevOps sequence is heavily preplanned in the PR bodies and cannot be counted as a corrective cascade merely because it is sequential.
6. The cohort is heavily confounded by graph-detector maturation, CI maturation, work-type changes, test-suite growth, review changes, and limited follow-up time.

The repository does **not yet** establish from this review alone:

- that graph-assisted development caused higher PR quality;
- that graph-assisted development caused lower PR quality;
- that #460 is the correct single treatment boundary;
- that fewer visible corrective PRs imply fewer underlying defects;
- that longer/more structured PR bodies correspond to better repairs;
- that every graph-guided PR used graph evidence materially rather than ceremonially.

## 22. Required next adjudication work

1. Freeze a complete PR census with dates, merge state, changed files, additions/deletions, base/head ancestry, author type, and explicit references.
2. For every candidate parent-child relation, inspect body, diff, tests, comments/reviews, ancestry, and relevant source history.
3. Reconstruct graph capability availability per PR rather than use one intervention flag.
4. Recover/archive graph impact, proof-selection, completeness, and architecture-decision artifacts where available.
5. Code planned next slices separately from corrective descendants.
6. Code pre-merge replacement by stated/verified cause.
7. Measure semantic fragmentation depth and boundary movement, not merely descendant count.
8. Add comparable non-cascade pre-450 controls to avoid selecting only dramatic failures.
9. Apply right-censoring controls to recent PRs.
10. Preserve prospective incidents without steering the implementing agent toward a desired outcome.

## 23. Research integrity statement

This document intentionally stops at an evidence-bounded descriptive synthesis. Any later version that promotes a statement to a finding should cite the adjudicated rows and source evidence that justify the promotion and should retain disconfirming cases alongside supporting cases.
