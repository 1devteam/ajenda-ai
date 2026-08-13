# PR #428 — Durable Experience Consolidation acceptance matrix

## UPG / LAP review

**Responsibility.** `DurableExperienceConsolidationService` accepts no caller-authored
episode semantics. It reads canonical, tenant-owned learning-signal evidence; validates
artifact role and payload; adapts owner fields into `ExperienceEpisodeInput`; delegates
recurrence to Experience Intelligence and promotion decisions to Knowledge
Qualification; and delegates proposition history writes to Knowledge Ledger.

**Sources of truth.** `EvidenceRecord` is durable learning history;
`DecisionLearningSignal` is the payload contract; `evaluate_experience_set` owns
comparability, dependence and recurrence; `qualify_pattern_knowledge` owns promotion;
`record_knowledge_qualification` owns persistence and replay; Knowledge Lifecycle owns
current-state resolution. Database predicates discover candidates only.

**Dependencies.** EvidenceBridge establishes action and evidence-role provenance.
PostgreSQL tenant activation/RLS and an explicit tenant predicate protect reads. The
existing Experience, Qualification, Ledger, Lifecycle, action registry, ability catalog,
and tool authorization paths remain authoritative downstream.

**Possible pitfalls.** Cross-tenant reads; payload-shaped impostors; malformed canonical
artifacts; contradictory action provenance; duplicate episode materializations; shared
lineage; legacy signals without episode references; missing owner semantics; weak
attribution; counterexamples; persistence ordering; late arrival; partial ledger writes;
replay identity conflicts; unbounded N+1 reads; and evidence output that hides rejected
history.

**Invariants.** No Experience or Knowledge store is added. The active tenant is the only
tenant authority. Malformed canonical history fails closed and remains inspectable.
Legacy history is never upgraded. All directions reach Experience. `evaluated_at`, never
`EvidenceRecord.created_at`, provides epistemic chronology. Dependence is resolved before
recurrence. Only Qualification can promote and only Ledger can persist. The composition
action is an authorized `INTERNAL_WRITE`; unchanged input is replay safe. No lifecycle,
applicability, decision support, runtime execution, causal inference, or weight mutation
is introduced.

**Proof.** Unit tests cover role/payload validation, legacy adaptation, duplicate and
lineage dependence, weak evidence, counterexamples, unrelated partitions, chronology,
and replay. A PostgreSQL integration test covers tenant activation, cross-mission durable
rows, tenant isolation, late persistence, Ledger writes, and repeat invocation. Contract
and rollout validators prove action/ability registration and write classification.

**Rollback.** Remove the composition action, service, dedicated read query, and manifest.
Ledger history is immutable and remains valid; no migration or historical evidence
rewrite is introduced.

## Adversarial acceptance matrix

| Case | Adversary / input | Required observable result |
|---|---|---|
| A | Three semantically equal, strong, independent successful episodes | One supported candidate is qualified and delegated to Ledger without manual episode assembly. |
| B | Run unchanged tenant history repeatedly | Candidate, qualification and proposition identities remain stable; Ledger reports canonical replay rather than duplicate promotion. |
| C | Persist the same authoritative `DecisionEpisodeReference` repeatedly | One dependent logical episode group; persistence count cannot manufacture recurrence. |
| D | Multiple records share evidence lineage roots | Existing Experience dependence rules prevent strong independent recurrence. |
| E | Add an independent counterexample after support | Counterexample remains in the partition; refreshed Qualification/Ledger history reflects contested evidence. |
| F | Two independent strong contradictions | Existing Experience rules may produce `INVALIDATED`; composition neither suppresses nor reinterprets it. |
| G | Another tenant has identical semantics and hashes | Activated tenant plus explicit predicate excludes every foreign record. |
| H | Earlier `evaluated_at` is persisted later | Full history remains visible and Experience candidate bounds follow signal evaluation time. |
| I | Canonical action/role with invalid payload | Consolidation fails closed with record IDs in a malformed-history diagnostic; no Ledger write is committed. |
| J | Valid V1 signal has no `DecisionEpisodeReference` | It parses, uses bounded legacy identity, and gains no authoritative episode provenance. |
| K | Owner intervention, subject, or goal semantics are insufficient | Experience marks the episode unclassified/excluded; adapter does not infer a partition. |
| L | Many weak, temporal, caller-asserted, or unknown observations | Existing Experience/Qualification gates prevent strong qualified knowledge. |
| M | `created_at` ordering conflicts with `evaluated_at` | Output inspection order is deterministic by evaluation time/identity; persistence time has no epistemic role. |
| N | Relevant and unrelated semantic episodes coexist | Experience creates separate partitions; neither partition changes the other's counts. |
| O | Payload resembles a signal but action or evidence role is wrong | Reader does not accept it as canonical learning history. |
| P | Action metadata fields contradict one another | Candidate is diagnosed as malformed provenance and the operation fails closed. |
| Q | Ledger write fails after assessment | Transaction rolls back; no partial qualification/artifact persistence is claimed. |
| R | Thousands of candidate records | One bounded tenant/action query loads payload and embedded lineage; no per-signal repository queries occur. |

## Explicit non-goals

Applicability, Decision Support, StrategyEngine, execution, autonomous scheduling,
causal inference, weight adaptation, vector/LLM semantic authority, a new ontology, an
Experience database, a new Knowledge store, and direct lifecycle mutation are excluded.
