# Ajenda V1 Completion Ambiguity Audit Plan

**Status:** Ready to execute  
**Baseline:** `83ec47fde32ac1cd1262b1fbfce8f0ade07c8ab3` (`Merge pull request #425`)  
**Owner:** Ajenda architecture and delivery team  
**Method:** finished product → invariants → implementation truth → gaps → dependency graph → remaining slices

## 1. Decision and purpose

Pull request #425 is present in the audited checkout. This document freezes its merge commit as the starting point for a single, completion-oriented ambiguity audit. It is an execution plan, not the audit result, a roadmap-derived feature list, or evidence that Ajenda V1 is complete.

The audit must answer:

> If the resulting Remaining Build Contract is executed correctly, what exactly will Ajenda be capable of, and what is the smallest dependency-ordered sequence that reaches that state without unresolved architectural debt?

The repository wins whenever implementation, migrations, tests, runtime proof, and prose disagree. Existing plans and PR descriptions are discovery aids only. No predicted PR count, previously proposed next slice, or aspirational product description constrains the result.

## 2. UPG/LAP preflight

### Responsibility

The audit accepts the frozen repository state and produces evidence-backed architectural findings and implementation-ready remaining-build contracts. It does not alter runtime behavior, promote knowledge, infer missing semantics, or grant execution authority.

### Sources of truth

Evidence is ranked in this order:

1. implementation, migrations, current tests, and reproducible runtime proof;
2. `PROJECT_SPEC.md` and enforced contract validators;
3. code-aligned architecture and authority contracts;
4. product documents and accepted ADRs;
5. historical PR descriptions, roadmaps, and assessments.

A higher-numbered source may locate a claim, but cannot prove it when a higher-ranked source disagrees or provides no implementation path.

### Dependencies

- Frozen Git SHA and recent landed history.
- API routes, domain models, services, repositories, workers, actions, migrations, and configuration.
- Unit, contract, deployment, integration, and live-proof surfaces.
- `PROJECT_SPEC.md`, `docs/architecture/SYSTEM_ARCHITECTURE.md`, ADRs, policies, and the authority ledger.
- Runtime queue, lease, dispatcher, tenant-session, policy, evidence, and audit contracts.

### Possible pitfalls

- Mistaking documentation, type existence, or green unit tests for a connected product capability.
- Treating missing proof as missing implementation, or compatibility debt as a required feature.
- Inferring semantic identity from IDs, prose, labels, timestamps, or storage order.
- Treating repeated or similar records as independent evidence.
- Designing Applicability before proving a typed current-context authority exists.
- Letting intelligence output become policy or bypass governed runtime admission.
- Expanding V1 until it includes every useful future improvement.
- Producing an attractive dependency graph whose edges are not backed by concrete contracts.

### Invariants

- Every finding cites repository or runtime evidence and records contrary evidence.
- Every product transition has one owner, one crossing contract, bounded downstream inference, and fail-closed behavior.
- Tenant isolation, queue authority, lease ownership, policy gates, side-effect authorization, and evidence provenance remain non-negotiable.
- Epistemic confidence never increases merely through persistence, repetition, retrieval, or downstream restatement.
- Unknown lineage is not independent lineage; storage order is not event chronology.
- Intelligence may inform a governed decision but cannot directly authorize execution.
- No imperfection becomes required work unless it blocks the defined V1 acceptance contract.
- No implemented layer is accepted solely because its local tests pass.

### Proof

The audit is accepted only when all five deliverables in section 7 exist, every mandatory transition has a completed boundary record, every required slice has a traceable finding and exit invariant, and the whole-pie matrix contains no unexplained red cell.

## 3. Provisional product hypothesis

The following is a hypothesis to test, not a frozen requirement:

Ajenda accepts a tenant-scoped business objective, represents its measurable meaning, creates governed executable work, executes through queue- and lease-authoritative runtime boundaries, records trustworthy evidence and outcomes, evaluates and attributes contribution conservatively, forms experiences without confusing repetition with independent support, qualifies bounded durable knowledge, determines whether that knowledge applies to a new typed context, and allows applicable knowledge to inform a later decision that must still pass normal runtime governance.

The audit may narrow or refine this statement where current repository contracts establish a more precise V1 boundary. Any refinement must be recorded with evidence and explicit non-goals.

## 4. Mandatory boundary model

The initial closed-loop hypothesis is:

```text
Intent / business objective
  → Mission
  → Goal + KPI semantics
  → Decision / plan
  → Governed materialization
  → Runtime admission
  → Execution
  → Evidence
  → Observed outcome + evaluation
  → Attribution
  → Decision feedback
  → Experience
  → Recurrence / pattern
  → Knowledge qualification
  → Durable knowledge
  → Lifecycle resolution
  → Knowledge retrieval
  → Applicability
  → Knowledge-informed decision
  → New governed execution
  → New evidence and outcome
  → Learning without semantic or causal inflation
```

Each arrow receives a boundary record containing:

| Field | Required answer |
| --- | --- |
| Upstream owner | Component that owns the source truth. |
| Crossing artifact | Exact typed/persisted artifact, schema version, identity, and provenance. |
| Transition owner | Only layer allowed to legitimize the transition. |
| Preconditions | Tenant, state, authority, evidence, chronology, independence, and policy requirements. |
| Preserved information | Semantics and provenance that downstream behavior depends on. |
| Deliberately discarded information | Data excluded to prevent accidental authority or unstable identity. |
| Allowed inference | Exact conclusions downstream layers may draw. |
| Forbidden inference | Reconstruction, causal, semantic, or authority claims downstream must not make. |
| Fail-closed behavior | Result when identity, lineage, chronology, semantics, authority, or evidence is insufficient. |
| Persistence | Durable owner, deterministic projection, or intentionally transient status. |
| Proof | Tests, migration checks, runtime evidence, and adversarial cases. |
| Status | Proven, under-proven, ambiguous, wrong, missing, compatibility debt, drift, or post-V1. |

If an arrow cannot be completed without assumptions, it remains an explicit blocking ambiguity; it cannot be silently bridged in the finished-product narrative.

## 5. Audit execution phases

### Phase 0 — Freeze and inventory

1. Record the baseline SHA, merge ancestry, migration heads, feature flags, and generated-contract status.
2. Capture the repository tree by architectural area rather than by filename alone.
3. Build a claim index linking product/architecture statements to candidate implementation and proof.
4. Record any local or environment limitation before interpreting absent runtime proof.

**Exit:** The audit can be reproduced from the frozen SHA, and every later finding identifies the exact baseline.

### Phase 1 — Reconstruct actual topology and authority

Trace these areas end to end: mission intake; business ontology; goals and KPIs; decision/planning; graph and task materialization; queue admission; execution coordination; worker leases; tools/providers; evidence; outcomes; evaluation; attribution; feedback; Experience; semantic coherence; Knowledge Qualification; ledger; lifecycle; Retrieval; abilities; tenant persistence; governance; and product-facing composition.

For each consequential decision, identify the enforcement point before consulting the existing authority ledger. Classify it as semantic authority, runtime authority, persistence authority, read-model authority, API adapter, compatibility adapter, governance boundary, or non-authoritative/future surface. Compare the independently derived map with the ledger only afterward.

**Exit:** Every major decision has zero or one demonstrated owner. Zero owners become missing/ambiguous findings; multiple owners become ambiguity findings.

### Phase 2 — Trace semantic and epistemic escalation

Trace exact-instance identity, semantic-object identity, objective/goal/KPI/intervention identity, subject and relationship scope, evidence lineage, outcome meaning, attribution provenance, recurrence context, proposition identity, and knowledge identity.

Then prove the gates between observation, evidence, evaluated outcome, feedback, experience, recurrence, qualified knowledge, current knowledge, retrieved knowledge, applicable knowledge, and decision influence. Search for:

- prose-, label-, status-, or raw-ID-derived classification;
- DB UUIDs, tenant IDs, clocks, or arrival timestamps inside semantic identity;
- duplicate signals represented through different records;
- shared decision, object instance, evidence, or derivation lineage counted independently;
- unknown lineage treated as independent;
- lower-confidence facts strengthened by storage, recurrence, or retrieval;
- downstream layers reconstructing semantics an upstream owner should provide.

**Exit:** Every epistemic promotion has an explicit owner, minimum input strength, independence rule, deterministic identity rule, and fail-closed counterexample.

### Phase 3 — Audit chronology, tenancy, persistence, and observability

Independently inspect:

- event/source/evaluation watermarks versus `created_at`, insertion order, UUID order, or latest-row shortcuts;
- late-arriving and superseded history behavior;
- tenant identity origin, HTTP activation, runtime activation, explicit repository filtering, RLS reinforcement, and action-context authority;
- persistence requirements across process boundaries and intentionally transient projections;
- inspected-record, algorithm/version, limitation, authority, and downstream-effect evidence;
- additive migrations, JSONB bridges, duplicate columns, constraints, seeds, RLS upgrade/downgrade behavior, and schema parity.

Identical semantic artifacts in two tenants, stale events arriving late, missing lineage, partial writes, retries, and duplicate representations are mandatory adversarial scenarios.

**Exit:** No required artifact depends on process memory accidentally, no event authority depends on storage order accidentally, no caller-supplied tenant value becomes authority, and all critical transitions are explainable after the fact.

### Phase 4 — Audit runtime separation and product composition

Prove that intelligence, catalog, adapter, retrieval, and recommendation surfaces cannot execute directly. Trace a prospective knowledge-informed decision back through mission/runtime governance, including permissions, quota, approval, policy, coordinator, queue, lease, dispatcher, provider, idempotency, compensation, evidence, and audit behavior.

Determine which implemented intelligence capabilities are reachable from governed product paths, which are intentionally callable-only, and which are accidentally isolated. Do not demand autonomous wiring where a bounded action surface is the intended V1 contract.

**Exit:** Knowledge can influence only the decision surface authorized by its contract, and any resulting work still enters the single authoritative runtime path.

### Phase 5 — Audit the future-facing seams without presupposing solutions

1. **Retrieval → Applicability:** Determine whether current context has a typed owner for subject, goal/KPI, intervention, relationships, scope, invalidation, state, and freshness. Applicability cannot evaluate prose or invent missing context.
2. **Applicability → Decision Support:** Identify the decision artifact, option/intervention semantics, conflict/absence representation, provenance preservation, and whether knowledge is advisory or part of an existing score.
3. **Decision Support → Adaptation:** Separate making knowledge available from mutating weights, policies, strategies, planner behavior, or capability selection. Establish the narrow V1 learning authority, if any.
4. **Planning ↔ Abilities:** Verify whether action selection has the typed dependency and compatibility semantics required by the accepted V1 loop; do not manufacture an Ability Graph without evidence.

**Exit:** Each seam is classified as already proven, under-proven, ambiguous, genuinely missing, or post-V1 before any implementation slice is proposed.

### Phase 6 — Negative-space and proof-quality audit

Verify that Ajenda does not silently perform causal inference, prose-derived semantic inference, automatic knowledge promotion, autonomous policy creation, unauthorized execution, unbounded memory, vector-based semantic authority, cross-tenant reasoning, or weak-evidence amplification.

Classify tests as implementation, contract, adversarial, integration, or canonical end-to-end proof. Reject synthetic fixtures that create states the owning layer could never produce. Identify layers with substantial local coverage but no proof of their real product transition.

**Exit:** Required absences have tests or enforceable boundaries, and every accepted capability has transition-level rather than merely module-level proof.

### Phase 7 — Classify findings and construct the remaining DAG

Every finding receives exactly one primary classification:

1. correct and adequately proven;
2. implemented but under-proven;
3. implemented but architecturally ambiguous;
4. implemented but semantically wrong;
5. genuinely missing capability;
6. compatibility debt;
7. documentation/test drift; or
8. legitimate post-V1 improvement.

Only findings that block the accepted V1 product hypothesis enter the required DAG. Combine changes when separate merges would create an unsafe intermediate state. Separate changes when combined ownership would obscure authority. Optimize for correctness first and implementation rediscovery cost second—not for a target number of PRs.

**Exit:** Every required DAG node traces to one or more blocking findings, and every blocking finding is resolved by exactly one node or an explicit dependency chain.

### Phase 8 — Write contracts and capstone proof before implementation

Write an AICP contract for every required node using section 7.4. Design the capstone scenario before the final implementation slices so their exit invariants converge on system completion rather than local success.

The capstone must include:

- one realistic objective traversing the full accepted V1 chain;
- a later, distinct but semantically comparable context;
- earned knowledge available to the second decision with provenance intact;
- normal runtime governance for the second execution;
- an apparently relevant knowledge item rejected because applicability is not earned;
- weak/dependent/chronologically uncertain evidence that cannot be amplified into stronger knowledge;
- cross-tenant semantic equality that never crosses the tenant boundary.

**Exit:** The capstone identifies the authoritative artifact and failure behavior at every transition and maps each assertion to an executable proof owner.

## 6. Search and evidence protocol

The audit uses layered searches, followed by complete-file reading and call-chain tracing. Search hits are leads, not findings.

Required search families include:

- authority words: `authority`, `canonical`, `owner`, `source_of_truth`, `compat`, `deprecated`;
- unfinished seams: `TODO`, `FIXME`, `placeholder`, `future`, `temporary`, `legacy`, `fallback`;
- semantic reconstruction: parsing/classifying names, labels, descriptions, free text, status, and arbitrary IDs;
- chronology: `created_at`, ordering, `latest`, watermarks, source/evaluated/event timestamps;
- independence/lineage: signal IDs, evidence IDs, parent/derivation IDs, decisions, object instances, deduplication;
- tenant paths: tenant parameters, runtime context, DB session activation, repository filters, RLS policies;
- runtime effects: enqueue, claim, lease, dispatch, execute, retry, idempotency, compensation, commit;
- epistemic terms: confidence, causal, correlation, recurrence, qualification, applicability, invalidation, current;
- persistence parity: domain/Pydantic/ORM/migration/seed representations;
- reachability: action registration, ability declaration, route/service callers, worker handlers, and consumers.

For every candidate seam, record:

- claim and severity;
- exact source locations and complete call path;
- positive and negative proof;
- owner and affected boundaries;
- tenant, side-effect, evidence, migration, retry, and compatibility impact;
- whether it blocks V1 and why;
- remediation class without prematurely prescribing a file patch.

## 7. Required audit deliverables

### 7.1 System Truth Map

An implementation-derived map of owners and transitions. Each entry includes authority class, accepted inputs, outputs/effects, persistence, tenant enforcement, callers, consumers, prohibited behavior, and proof. It includes the completed boundary records from section 4.

### 7.2 Ambiguity Register

Each item includes a stable ID, classification, severity, evidence, contrary evidence, affected transition, architectural owner, product consequence, V1-blocking rationale, compatibility considerations, and proposed resolution owner. Unverified suspicions remain explicitly marked and cannot drive a required PR.

### 7.3 Remaining Capability DAG

Each node is an independently coherent capability or mandatory hardening outcome. Nodes are labeled:

- `REQUIRED-CAPABILITY`: the accepted V1 loop cannot work without it;
- `REQUIRED-HARDENING`: behavior exists, but ambiguity or missing proof prevents trustworthy completion;
- `POST-V1`: valuable, explicitly excluded from V1 completion.

Edges identify the concrete contract or invariant supplied to the dependent node. A visual edge without a stated dependency is invalid.

### 7.4 AICP Contract Set / Remaining Build Contract

Every required PR contract contains:

1. PR title and branch name;
2. completion class;
3. exact finished-product capability unlocked;
4. blocking finding(s) and why the PR must exist;
5. dependencies and supplied downstream contract;
6. owning architectural layer and authority class;
7. input/output contracts and types to change;
8. expected propagation/call path;
9. tenant, side-effect, evidence, chronology, independence, persistence, migration, and retry impacts;
10. exact semantic rules and fail-closed behavior;
11. compatibility and rollback requirements;
12. likely files, based on traced call sites rather than filename guesses;
13. adversarial acceptance scenarios;
14. canonical integration proof;
15. validation matrix and required runtime proof;
16. forbidden shortcuts and explicit non-goals;
17. documentation/authority-ledger updates after implementation proof; and
18. one testable **exit invariant** that tells the implementer when to stop.

No contract may leave ownership, semantic identity, tenant source, side-effect class, persistence, or failure behavior for the implementation agent to rediscover.

### 7.5 Whole-Pie Acceptance Contract

The final contract narrates a representative objective through every accepted transition. For every arrow it names what crosses, who owns it, what proves it, what information survives, and how missing or conflicting truth fails closed.

Its matrix covers at minimum: owner known; contract typed; tenant-safe; deterministic where required; persistence appropriate; chronology authoritative; independence enforced; fail-closed ambiguity; adversarial proof; real integration proof; governance evidence; and downstream consumer.

Every red cell must map to required work. Every accepted V1 limitation must be bounded, justified, and mapped to `POST-V1`; it cannot be hidden as a note.

## 8. Validation ladder

Run narrow proof while investigating each boundary, then the repository gates after the audit artifacts are assembled. The audit records exact pass/fail/skip results and does not translate environment failures into product findings.

```bash
ruff check backend/ tests/ scripts/validation/
ruff format --check backend/ tests/ scripts/validation/
mypy backend/
python scripts/validation/contract_drift_check.py
python scripts/validation/migration_seed_contract_check.py
python scripts/validation/ability_rollout_contract_check.py
python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"
```

Add relevant integration, migration round-trip, and live-runtime checks wherever findings touch runtime, queues, leases, persistence, providers, side effects, or process boundaries. Documentation-only planning changes do not substitute for those later implementation proofs.

## 9. Audit completion and stop conditions

The ambiguity audit stops only when:

- all five deliverables exist and agree;
- every mandatory boundary has a completed record;
- every finding is classified once and backed by evidence;
- every V1 blocker maps to a dependency-ordered PR contract;
- every required PR has a bounded owner, negative scope, adversarial matrix, and exit invariant;
- no remaining PR exists merely because it was previously predicted;
- the capstone acceptance contract exercises the second, knowledge-informed governed execution and its rejection/weak-evidence counterexamples;
- the whole-pie matrix has no unexplained red cell; and
- a final ambiguity search finds no known V1-blocking duplicate authority, downstream semantic reconstruction, chronology error, dependence inflation, tenant leak, execution bypass, or disconnected mandatory transition.

After implementation of the resulting DAG, repeat the ambiguity searches against the new `main`, update the code-aligned system architecture, document bounded V1 limitations and the explicit V2 backlog, and freeze V1. Software may continue to improve; completion means the accepted product contract is satisfied without known blocking ambiguity.

## 10. Explicit non-goals of this planning artifact

- It does not claim that Applicability, Decision Support, Adaptation, an Ability Graph, memory promotion, or any previously predicted slice is required.
- It does not claim the provisional product hypothesis is already supported by current contracts.
- It does not assign a PR count before the audit evidence exists.
- It does not alter runtime, schemas, authority, tenant behavior, side effects, or release policy.
- It does not treat the plan itself as any of the five audit deliverables.
