# PR #429 — Knowledge Applicability Resolution acceptance contract

> **Semantic relevance is not applicability. Applicability must be earned from explicit current-context assertions against the knowledge proposition's preserved scope and invalidation conditions. Missing context is unknown, not false.**
>
> **Ajenda may determine applicability only from typed current-context assertions and owner-produced semantic contracts. It may not infer applicability from prose, free-form business-state attributes, absence of evidence, or an LLM judgment.**

## UPG / LAP review

### Responsibility and source of truth

The pure applicability layer accepts one canonical `RetrievedKnowledgeMatch` and one typed current context, compares only exact canonical condition keys, and emits an inspectable deterministic judgment. The production action obtains matches by invoking canonical Knowledge Retrieval under the active runtime tenant, evaluates every match once in memory, and emits read-only action evidence. Retrieval owns semantic relevance, Lifecycle owns current global authority, owner Goal and Business Object contracts own semantic comparison, and typed assertions own current condition truth.

### Dependencies

- Upstream: Knowledge Qualification proposition conditions; immutable Knowledge Ledger; Knowledge Lifecycle; Knowledge Retrieval; Business Object and Goal semantic owner contracts; `ObservationVerificationBasis`; active tenant session.
- Composition: `knowledge.evaluate_applicability` action, action registry, ability manifest/catalog, and EvidenceBridge-compatible `EvidenceItem` output.
- Proof: pure adversarial unit tests, action/manifest/authority contract tests, and real PostgreSQL Ledger → Lifecycle → Retrieval → Applicability integration proof.
- Persistence: none. No migration or applicability table is introduced.

### Possible pitfalls

Wrong or missing conditions, duplicate assertions, mismatched exact-subject classes, query/context goal disagreement, caller-authored retrieval artifacts, cross-tenant reads, non-ACTIVE lifecycle state, corrupt stored knowledge, zero retrieval matches, arbitrary input ordering, weak assertion provenance, misleading inspection claims, and accidental lifecycle/ledger/runtime mutation must all fail closed or remain explicitly limited.

### Invariants

1. Retrieval remains unchanged and continues returning `applicability_determined=false`.
2. Only exact condition-token identity is evaluated; prose, fuzzy matching, LLM inference, and `BusinessStateSnapshot.attributes` are not inputs.
3. Missing and explicit `UNKNOWN` condition truth produce insufficient context, never a false assertion.
4. Active contextual invalidation wins precedence but never mutates global lifecycle state.
5. Partial Goal equivalence can produce at most `PARTIALLY_APPLICABLE`.
6. Duplicate condition keys and incoherent exact/semantic subjects are rejected before evaluation.
7. Identities and outputs are invariant to assertion ordering and change when epistemically relevant context changes.
8. Production composition activates the runtime tenant and runs one canonical retrieval query, then performs no database write.
9. Evidence distinguishes database records inspected by Retrieval from opaque assertion evidence merely referenced.
10. Applicability is neither policy, decision support, decision instruction, ranking, planning, nor execution authority.

### Proof and rollback

The matrix below maps invariants to deterministic tests. The PostgreSQL integration test snapshots ledger rows before and after evaluation and proves tenant isolation. Contract validation proves manifest and authority-ledger alignment. Rollback is code-only: remove the evaluator, action, manifest, exports, tests, and documentation; no stored data requires reversal.

## Adversarial acceptance matrix

| Scenario | Expected proof |
|---|---|
| Fully equivalent Goal; every scope ACTIVE; every invalidation INACTIVE | `APPLICABLE`; matched assertion evidence preserved |
| Required scope INACTIVE | `NOT_APPLICABLE`; Knowledge remains lifecycle-ACTIVE |
| Required scope UNKNOWN | `INSUFFICIENT_CONTEXT` |
| Required scope absent | `INSUFFICIENT_CONTEXT`; absence is not INACTIVE |
| Declared invalidation ACTIVE | `INVALIDATED`; no Lifecycle mutation |
| Declared invalidation INACTIVE | Condition appears in cleared invalidations |
| Declared invalidation UNKNOWN or absent | `INSUFFICIENT_CONTEXT` |
| No proposition conditions and equivalent Goal | `APPLICABLE` without manufactured context requirements |
| Partial Goal equivalence with all conditions proven | `PARTIALLY_APPLICABLE`, never `APPLICABLE` |
| Unrelated assertions | No status or identity effect beyond relevant assertion set |
| Duplicate same-state or contradictory condition assertions | Context validation failure; no list-order resolution |
| Exact subject types disagree with semantic subject classes | Context validation failure |
| Assertion exact subjects fall outside current exact context | Context validation failure |
| Query and context Goal or subject semantics disagree | Production input validation failure before retrieval |
| Cross-tenant stored knowledge | No match/evaluation under the active tenant |
| Malformed stored artifact or authority linkage | Existing Retrieval integrity failure remains fail-closed |
| Lifecycle state is not ACTIVE | No Retrieval match and therefore no applicability evaluation |
| No semantic Retrieval match | Empty evaluations plus `no_current_semantic_knowledge_match` |
| Active invalidation and inactive scope coexist | `INVALIDATED` by frozen precedence |
| Deterministic replay | Same semantic inputs produce the same applicability/resolution IDs |
| Reordered assertions, subjects, or evidence IDs | Canonical output and IDs remain unchanged |
| Changed relevant assertion state/evidence/time | Different applicability/resolution ID |
| Caller-asserted or UNKNOWN verification basis | Assertion may establish state but emits an epistemic limitation |
| Source-supplied/system-derived/independently verified basis | Basis is preserved without a new trust-ranking system |
| Empty assertion evidence list | Allowed and inspectable; no evidence is fabricated |
| Assertion evidence IDs | Reported as referenced evidence, not database records inspected |
| Production action | `INTERNAL_READ`, tenant-scoped, auditable, evidence-required, disabled by default |
| Ledger immutability | Qualification/artifact row counts and payloads unchanged after every status |

## Explicit non-goals

No Decision Support, ranking, score mutation, mission/task creation, queueing, runtime execution, Lifecycle or Ledger mutation, Qualification, Experience, causal inference, StrategyEngine, policy generation, fuzzy/LLM classification, event-stream state reconstruction, generic rules engine, applicability database, or automatic global invalidation is included.
