# PR #430 — Knowledge-Informed Decision Support Acceptance

## Primary invariants

> Applicable knowledge may inform a decision only as bounded, provenance-preserving evidence. Knowledge does not become policy, does not select an option, does not rewrite decision criteria or weights, and does not acquire execution authority.

> Ajenda's own derived knowledge must never recursively manufacture independent evidence for itself. Knowledge-informed decision support may cite prior knowledge, but that citation cannot later be counted as a new independent observation supporting the same knowledge proposition.

## UPG / LAP review (completed before implementation)

- **Responsibility:** accept a Decision-owned request containing typed options and criteria plus Retrieval/Appplicability inputs; invoke canonical tenant-scoped Retrieval and Applicability; translate eligible, exactly aligned propositions into bounded derived evidence; pass that evidence to `decision.recommend_next_action`; return support and Decision results separately.
- **Sources of truth:** `KnowledgeProposition` owns intervention, objective/KPI, and relationship semantics; `KnowledgeRetrievalResult` owns current ACTIVE knowledge; `KnowledgeApplicabilityResolutionResult` owns current-context eligibility; `DecisionOption`, `DecisionCriterion`, `EvidenceFact`, and `decision.recommend_next_action` own decision semantics and scoring; `EvidenceLineage` owns derived-versus-observational provenance; the active runtime context owns tenant authorization.
- **Dependencies:** Knowledge Ledger repository and RLS session; Lifecycle projection; Retrieval query/matcher; Applicability context/resolver; Decision action contracts/evaluator; EvidenceBridge; ability registry/manifests; authority ledger; episode/Experience lineage consumers.
- **Possible pitfalls:** caller-forged authority artifacts; foreign-tenant reads; missing/fuzzy option or criterion identities; status-to-number conversion; hidden weight or score mutation; invalid/future applicability; unstable identities from ordering; duplicate action evidence; derived evidence becoming an independent recurrence root; suppression of genuinely new outcome observations; lifecycle mutation; alternate recommendation authority.
- **Invariants:** exact canonical identity matching only; missing semantics fail unresolved; only APPLICABLE/PARTIALLY_APPLICABLE can emit Decision evidence; partial status remains a limit; no weights are changed or invented; all support lineage closes over Knowledge's original evidence roots; support is derived, non-policy, non-decision, and non-executable; tenant scope is RLS plus explicit predicates; evaluation chronology is monotonic; replay is deterministic.
- **Proof:** pure evaluator unit tests; action composition/registry/manifest tests; EvidenceBridge and Experience-lineage adversarial tests; real PostgreSQL Ledger→Lifecycle→Retrieval→Applicability→Support proof including tenant exclusion and immutable row counts; Decision episode provenance test; full contract and validation ladder; final global alternate-path search.
- **Persistence / rollback:** no table or migration is introduced. The action performs tenant-scoped reads only; rollback is removal of the additive action, manifest, evaluator, and documentation.

## Adversarial acceptance matrix (written before implementation)

| Case | Attack / condition | Required bounded result | Proof target |
|---|---|---|---|
| A | Applicable favorable proposition exactly matches option and criterion semantics | `SUPPORTS` only for that option/criterion; Decision remains canonical | evaluator + PostgreSQL |
| B | Explicit owner-produced unfavorable relationship exactly matches | `OPPOSES`; never infer opposition from a different supported option | evaluator |
| C | `PARTIALLY_APPLICABLE` with exact alignment | Direction preserved with `partial_applicability`; no numeric weakening | evaluator |
| D | `INSUFFICIENT_CONTEXT` | `UNRESOLVED`, excluded from Decision evidence, reason retained | evaluator |
| E | `NOT_APPLICABLE` | considered-but-excluded; no Decision evidence | evaluator |
| F | `INVALIDATED` | no positive/opposite inference and no Lifecycle mutation | evaluator + PostgreSQL |
| G | Option lacks canonical intervention identity | `UNRESOLVED`; label/description ignored | evaluator |
| H | Unrelated intervention | `NEUTRAL`; objective overlap cannot create support | evaluator |
| I | Criterion semantic identity differs | no criterion evidence; no label inference | evaluator |
| J | Exact replay and reordered options/criteria/matches | stable influence/support identities and output ordering | evaluator + PostgreSQL |
| K | World evidence A → Knowledge K → support D → later learning input | D remains derived from A and cannot become independent root | Experience adversarial regression |
| L | Knowledge-informed decision later produces new source observation B | B remains independently eligible; participation of K does not suppress it | Experience regression |
| M | Tenant B has semantically identical knowledge | invisible to tenant A under RLS and explicit predicates | PostgreSQL |
| N | Applicability time is after support time | fail closed | evaluator |
| O | Caller supplies Retrieval/Applicability/qualified artifact JSON | production input rejects extra authority artifacts and recomputes owners | input/action test |
| P | Attempt to modify criterion weight or add knowledge bonus | original criterion contract forwarded unchanged; no support arithmetic | action spy + search |
| Q | EvidenceBridge persists support | lineage says derived/system computation and retains roots/parents | bridge test |
| R | Decision episode materializes recommendation | knowledge/applicability/influence IDs remain provenance, not outcome roots | episode test |
| S | Action invoked outside queue/dispatcher contracts | no alternate route; registry action remains declarative and `INTERNAL_READ` | registry/manifest/search |

## Explicit non-goals

No StrategyEngine, causal inference, policy promotion, autonomous decision making, weight learning, runtime execution, mission/task creation, fuzzy semantics, lifecycle mutation, or new persistence authority.
