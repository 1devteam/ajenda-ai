# Ajenda V1 — five finish-line options

**Decision owner:** Obex Blackvault  
**Prepared:** 2026-08-18  
**Implementation baseline:** `main@7ccadea5a9da7700ccf9b0ccd6087c027bff9a12` plus the audited
planning/validation branch  
**Status:** Path 3 selected on 2026-08-18; selection authorizes scope, not implementation completion

**Owner decision:** Obex Blackvault authorized **Path 3 — Single Vertical Worker V1** with the
Revenue Operations boundary of research, qualification, personalized draft preparation, human
approval, and optional provider-backed delivery/CRM update. The decision record and remaining
promotion decisions are maintained in
[`D8_REVENUE_OPERATIONS_V1_DECISION.md`](D8_REVENUE_OPERATIONS_V1_DECISION.md).
The code-derived capability baseline is maintained in
[`VR01_REVENUE_OPERATIONS_BASELINE.md`](VR01_REVENUE_OPERATIONS_BASELINE.md).

**Current-state prerequisite:** read
[`docs/planning/CURRENT_COMPETENCY_AND_RUNTIME_MAP.md`](CURRENT_COMPETENCY_AND_RUNTIME_MAP.md) for
the implementation-grounded competency breakdown, runtime definition, intelligence chain, and the
actual contribution of the second runtime-authority spine before selecting a path.

**Next-thread planning handoff:** use
[`docs/planning/NEXT_THREAD_V1_PLANNING_PROMPT.md`](NEXT_THREAD_V1_PLANNING_PROMPT.md) to start the
implementation-planning thread with the accumulated audit, competency, authority, remediation, and
V1 decision context while requiring every claim to be reverified against current code.

## 1. Decision to make

“Finished V1” is not one self-evident state. Ajenda can finish as a safe runtime foundation, a
bounded Brain/copilot, one valuable vertical worker, a governed specialist swarm, or a broad
horizontal platform. These are different products with different proof burdens. Trying to call all
five “V1” would recreate the current problem: many nouns and contracts without one complete user
outcome.

All paths inherit the non-negotiable platform floor:

1. converge the daemon and synchronous HTTP mission-bridge claim/start/run authorities;
2. close stranger-facing P0 auth, RBAC, browser-secret, plan, RLS, and ingress findings;
3. make enabled external effects replay-safe or visibly `effect_unknown`;
4. preserve tenant isolation, queue authority, lease ownership, policy/review, evidence, and audit;
5. prove the selected product promise through real PostgreSQL/Redis and production-like deployment;
6. publish explicit exclusions rather than carrying unfinished surfaces as implied features.

The paths below change what comes **after and alongside** that floor. Calendar estimates are not
included because verified capacity, provider access, production topology, and migration volume are
not available. Sequence and exit artifacts are provided instead.

## 2. Comparison

| Path | V1 customer promise | Uses complex-prompt planning | Uses swarming | External effects | Relative scope | Product-value fit |
|---|---|---:|---:|---:|---:|---|
| 1. Runtime Foundation | “A secure governed execution API for explicitly constructed tasks.” | No | No | Limited to proven actions | Smallest | Infrastructure/API buyers |
| 2. Brain Operator | “Ajenda researches, reasons, drafts, and organizes internal work with evidence.” | Bounded | No | None by default | Small–medium | Fastest visible intelligence product |
| 3. Vertical Worker | “Ajenda completes one named business workflow from prompt to deliverable.” | Yes, within one vertical | No | Only vertical-approved effects | Medium | **Recommended V1** |
| 4. Vertical Swarm | “Multiple governed specialists collaborate to complete one vertical workflow.” | Yes | Yes, graph-bound | Only vertical-approved effects | Large | Differentiated multi-agent product |
| 5. Horizontal Mission Platform | “Customers compose many verticals/providers on one governed runtime.” | Broad | Optional | Broad provider set | Largest | Platform strategy, latest credible finish |

## 3. Path 1 — Runtime Foundation V1

### Product boundary

Ship Ajenda as a tenant-scoped governed runtime/API. Customers or internal callers explicitly
construct missions/tasks and invoke registered actions. Do not promise natural-language mission
decomposition, autonomous advancement, Brain competence, or agent collaboration.

### Build sequence

1. Complete containment and PR-01 through PR-13 from the remediation plan.
2. Converge runtime authority under PR-07/PR-08: daemon workers become the sole claim/start/run
   authority; HTTP worker endpoints become read/preview/trigger adapters without synchronous
   dispatch.
3. Enable only actions with complete schema, authority, credential, evidence, and replay contracts.
4. Finish operator auth, tenant-bounded recovery, forced RLS, browser-session replacement, billing
   reconciliation, and production ingress.
5. Update SDK/API examples around explicit `ExecutionTask` submission and evidence retrieval.

### V1 exit proof

- P0 and P1 release gates pass.
- Runtime authority inventory contains no `competing_http_spine` or `exception_bypass` entries.
- Real two-tenant PostgreSQL/Redis race, rollback, lease-expiry, recovery, and queue-corruption
  matrix passes.
- Every enabled write action proves idempotent retry or `effect_unknown` reconciliation.
- Production-like API client completes an explicit task and retrieves terminal evidence.

### Explicit exclusions

- No claim of complex-prompt competence.
- No autonomous mission planning or replanning.
- No swarm/fleet execution.
- Brain remains an action/provider catalog, not a product-level reasoning runtime.

### Trade-off

This is the smallest defensible V1 and the best substrate for every later option, but it does not
solve the product problem Obex identified: customers still need to know how to decompose work.

## 4. Path 2 — Brain Operator V1

### Product boundary

Ship a bounded internal-work copilot that can interpret supported research, retrieval,
qualification, drafting, document, calendar-read, and CRM-read intents; assemble an evidence-backed
deliverable; and ask for clarification when the request is unsupported. External sends, publishes,
generic writes, and free-running loops are off by default.

### Build sequence

1. Complete Path 1's runtime/security floor.
2. Execute VR-01 against a Brain Operator acceptance corpus focused on internal/read-only work.
3. Reconcile `BRAIN_MISSIONS`, Mission Composition outcomes/jobs, ability manifests, registered
   actions, action input/output schemas, and provider provenance into one versioned capability map.
4. Implement VR-02/VR-03 bounded know-how and hybrid planning for the supported intent set.
5. Implement VR-04 typed artifact binding and final deliverable assembly on the canonical worker
   spine.
6. Provide one customer UI for prompt, clarification, plan preview, progress, sources, limitations,
   and deliverable download/readback.

### V1 exit proof

- Sealed held-out prompts meet owner-approved clause-coverage, clarification, refusal, factuality,
  provenance, completion, latency, and cost thresholds.
- Full HTTP prompt → composition → confirmation → task graph → queue → lease → dispatcher → tools →
  artifacts → deliverable proof passes across two tenants.
- Prompt injection through web/retrieved content cannot alter action or authority boundaries.
- No action output is labeled external/real without evidence of that provider path.

### Explicit exclusions

- No external send/publish promises.
- No general business workflow claim.
- No multi-agent collaboration; parallel task execution alone is not marketed as swarming.

### Trade-off

This creates visible intelligence sooner and minimizes external-effect risk. It is a better product
than Path 1 but still risks being perceived as another copilot rather than a vertical worker.

## 5. Path 3 — Single Vertical Worker V1 (**recommended**)

### Product boundary

Ship one outcome-complete vertical: the selected scope is revenue operations from company/prospect
research through qualification, personalized draft preparation, human approval, and optional
provider-backed delivery/CRM update. The bounded job mapping and unresolved promotion thresholds
are recorded in the D8 decision record.

### Build sequence

1. Run the Path 1 security/runtime floor in parallel with VR-01 acceptance-corpus and capability
   inventory work.
2. Record D8: users, jobs, representative prompts, deliverables, providers, prohibited actions,
   approval points, budgets, escalation behavior, and numeric promotion thresholds.
3. Implement VR-02 versioned vertical know-how and VR-03 validated complex-prompt planning.
4. Complete PR-10/PR-11 authorization provenance and external-effect receipts for only the selected
   vertical's write/send actions; keep all other unsafe providers disabled.
5. Implement VR-04 typed artifact/dataflow execution and VR-05 bounded evaluate/replan behavior.
6. Complete VR-06 with one coherent mission UX and a production-like canary pilot.

### V1 exit proof

- P0/P1 and vertical-runtime gates pass.
- A sealed corpus proves direct prompts, paraphrases, compound goals, corrections, missing data,
  contradictions, long context, unsupported asks, and injection resistance.
- At least two tenants complete the named workflow from prompt to owner-defined final deliverable.
- Human approval, provider failure, crash-after-effect, partial completion, cancellation, bounded
  replan, and rollback scenarios pass.
- A published capability matrix states exactly which jobs/providers are proven and which remain
  plan-only.

### Explicit exclusions

- No “general autonomous employee” claim.
- No second vertical until it independently meets the same contract.
- No swarming claim; one planner may create parallel DAG tasks, but agents do not collaborate.

### Trade-off and recommendation

This is the best V1 balance. It directly addresses the inability to handle complex prompts, proves
one economically legible outcome, constrains provider and safety scope, and builds on the canonical
runtime rather than replacing it. It should be selected unless the defining V1 promise explicitly
requires multiple collaborating specialists.

## 6. Path 4 — Governed Vertical Swarm V1

### Product boundary

Ship Path 3 plus multiple durable, role-scoped specialists that collaborate through typed artifacts
on one vertical mission. “Agent” means accountable role projection; ordinary workers still execute
all nodes. There is no swarm queue, swarm worker, direct tool runner, or hidden peer-to-peer
authority.

### Build sequence

1. Complete Path 3 through VR-04; runtime convergence is a hard dependency.
2. Record D9: delegation topology, task creation authority, plan-revision authority, fan-out,
   depth, concurrency, shared context, conflicts, budgets, approvals, and result owner.
3. Harden existing fleet/agent persistence with tenant, mission, graph, role, know-how, and status
   invariants rather than creating a shadow agent domain.
4. Implement VR-07 graph-bound delegation, dependency-ready parallelism, typed artifact handoff,
   deterministic coordination/read models, conflict handling, aggregation, and reconstructable
   fleet/agent state.
5. Add VR-05 bounded replanning only if D9 authorizes the swarm to propose plan changes.
6. Ship swarm progress, role accountability, artifacts, conflicts, reviews, budgets, and aggregate
   result in the mission UX.

### V1 exit proof

- Every Path 3 proof passes.
- A real two-tenant scenario creates at least three role-scoped specialists, executes parallel and
  dependent nodes through ordinary workers, exchanges typed artifacts, holds high-risk work for
  review, and aggregates a final deliverable.
- Cross-tenant/mission/fleet/role assignment, artifact injection, fan-out/depth/budget overflow,
  duplicate scheduling, conflicting outputs, coordinator restart, fairness, cancellation, and
  `effect_unknown` tests pass.
- Runtime inventory and architecture sentinels prove no third runtime authority exists.

### Explicit exclusions

- No free-form peer-to-peer agent network.
- No mutable hidden conversation as execution authority.
- No agent-created credentials, approvals, or direct provider calls.
- No broad multi-vertical swarm claim.

### Trade-off

This is the most differentiated focused V1, but it adds distributed coordination and product UX
before a single-agent vertical has proven demand and quality. Choose it only if swarming itself is
the required market promise, not merely an implementation preference.

## 7. Path 5 — Horizontal Governed Mission Platform V1

### Product boundary

Ship a platform for multiple vertical packs, configurable providers, bounded planning/replanning,
optional governed swarms, customer capability administration, and production operator controls.

### Build sequence

1. Complete all required PR-01 through PR-16 remediation work.
2. Complete VR-01 through VR-06 for at least two materially different verticals; complete VR-07 if
   swarming is marketed.
3. Productize versioned know-how/vertical authoring, compatibility, tenant enablement, provider
   readiness, capability matrices, and migration/rollback tooling.
4. Prove quotas, worker fairness, cost controls, operator observability, support diagnostics,
   billing entitlements, and provider reconciliation across verticals.
5. Add author/publisher governance so declarative packs can never register runtime handlers or
   grant authority directly.

### V1 exit proof

- P0, P1, Knowledge (where claimed), vertical, and swarm (where claimed) gates pass.
- Two or more verticals pass independent sealed acceptance corpora and production-like pilots.
- Cross-pack action/schema/version conflicts, tenant enablement, migration, rollback, noisy-neighbor,
  provider outage, and cost-budget scenarios pass.
- Operator and customer documentation names supported combinations and rejects unsupported ones.

### Explicit exclusions

- No unreviewed marketplace code execution.
- No arbitrary plugin handler registration from tenant-authored metadata.
- No “works for every business process” claim.

### Trade-off

This maximizes the long-term platform vision but is the least useful V1 scope: it postpones a clear
finish until multiple vertical, provider, runtime, security, billing, and authoring systems are all
proven. It should be the post-V1 direction, not the default V1 choice.

## 8. Recommendation and decision rule

Select **Path 3 — Single Vertical Worker V1**.

It is the narrowest option that resolves the core product complaint—Ajenda does not yet know how to
turn complex prompts into completed work—while avoiding the unproven coordination cost of swarming
and the indefinite breadth of a horizontal platform. Implement Path 1's safety/runtime floor as a
dependency, not as the customer-facing finish line. Preserve Path 2 as a degraded/read-only mode
when credentials, approval, or provider guarantees are unavailable. Treat Path 4 as the first
post-V1 differentiator after the single vertical meets its quality and demand thresholds. Treat
Path 5 as the platform roadmap.

This recommendation is conditional on the integration changes in
[`docs/planning/CURRENT_COMPETENCY_AND_RUNTIME_MAP.md` section 10](CURRENT_COMPETENCY_AND_RUNTIME_MAP.md#10-will-the-recommended-v1-produce-the-coherent-powerful-ajenda-system).
Path 3 is not achieved by adding a vertical prompt pack to the current system. It requires one
semantic contract, one runtime authority, typed artifact flow, deliverable/outcome authority,
bounded replanning, independent side-effect authorization, and risk-proportional governance.

Use this decision rule if priorities differ:

- Choose **Path 1** when the buyer is an API/runtime integrator and product intelligence is not a V1
  promise.
- Choose **Path 2** when fastest safe visible intelligence matters more than autonomous completion.
- Choose **Path 3** when one finished business outcome and complex-prompt competence define V1.
- Choose **Path 4** only when governed multi-specialist collaboration itself defines V1.
- Choose **Path 5** only when funded capacity and committed design partners require multiple
  verticals before launch.

## 9. Owner decision record

Before implementation milestones are assigned, record:

1. selected path number and product promise;
2. selected vertical and D8 answers if Path 3–5;
3. D9 answers if Path 4 or swarm-enabled Path 5;
4. enabled providers and external effects;
5. numeric quality, safety, cost, and latency promotion thresholds;
6. named exclusions that sales, UI, docs, and API behavior must preserve.

Path 3 and its Revenue Operations boundary are authorized in the linked D8 record. Inventory,
acceptance-corpus design, and P0 containment may proceed. Release promotion remains blocked until
the open numeric quality, safety, cost, latency, and pilot decisions in that record are approved.
