# Preliminary PR Quality Analysis — PR #460 onward

**Status:** exploratory working analysis; not an empirical finding  
**Production comparison snapshot:** through PR #473  
**Population reconnaissance snapshot:** through PR #474  
**Document governance:** revisable working artifact; supersede/rewrite if the population analysis requires it

## Question

Do Ajenda PRs from the provisional graph-assisted period show a change in engineering quality, and what observable mechanisms might explain that change?

This note does **not** define quality by PR size, prose length, CI success, or absence of another PR within an arbitrary elapsed-time window. Fixed 7/14/30/60-day windows are censoring/sensitivity controls only. The companion `multivariate-pr-quality-framework-v0.1.md`, census schema, extraction method, and adjudication queue define the broader analysis.

## Dimensions used in this preliminary comparison

1. root-defect clarity;
2. semantic/blast-radius reasoning;
3. explicit invariant or architecture contract;
4. scope discipline and non-goals;
5. proof topology aligned to the failure mode;
6. architectural closure observability;
7. pre-merge interception/design supersession;
8. residual-defect visibility;
9. realized corrective propagation, semantic fragmentation, severity movement, and rework.

The first eight can be observed contemporaneously. The ninth requires causal reconstruction over later history.

## Cohort handling

### Production / architecture-process evidence reviewed

- #460 — authority-containment correction;
- #465 — password-signup verification correction;
- #468 — semantic graph hardening / measurement-system intervention;
- #469 — RLS/session-boundary correction;
- #470 — post-RLS graph certification;
- #471 — closed-unmerged idempotency design; process evidence only;
- #472 — durable HTTP idempotency authority;
- #473 — atomic single-use credential transitions.

### Excluded from product-quality comparison

- #461–#464 — dependency-maintenance PRs;
- #466 — research bootstrap;
- #467 — invalid prospective pilot/protocol execution error.

## PR-level preliminary assessment

| PR | Root defect | Semantic scope | Invariant | Proof topology | Graph closure | Scope discipline | Working assessment |
|---|---|---|---|---|---|---|---|
| #460 | strong | broad | moderate | strong | absent | strong | Major improvement in authority/ownership reasoning and regression proof, but closure remains implementation/test-centric. |
| #465 | strong | broad local contract | moderate | strong | absent | strong | Strong ownership-verification repair; later GF-14 shows the broader concurrency/single-use invariant remained open. This is not evidence that #465 introduced GF-14. |
| #468 | strong | semantic instrumentation | strong | strong | detector intervention | strong | Changes what the graph can observe: RLS, egress, state ownership/concurrency, known-violation visibility, and a semantic ratchet. |
| #469 | strong | cross-boundary | strong | strong real-DB proof | strong | strong | Migration and raw-session consumers are repaired together; graph closure proves the targeted RLS findings disappear. |
| #470 | N/A runtime | architecture adjudication | strong | semantic ratchet | strong | strong | Makes an intentional control-plane exception explicit while preserving remaining defects. |
| #471 | strong | broad | strong | strong planned | not realized | strong | Closed unmerged; narrower/different Redis ownership design. Preserve as pre-merge process evidence. |
| #472 | strong | clustered root cause | strong | very strong | very strong | very strong | Treats the HTTP idempotency cluster as one durable execution-ownership/operation-identity problem; includes real contention, recovery, encrypted replay and targeted graph closure. |
| #473 | strong | shared invariant | very strong | very strong | very strong | very strong | Groups GF-14/GF-22/GF-23 under atomic single-use successor-authority semantics and reuses existing durable rows as the locking authority. |

## Observed transition is staged, not binary

### Stage A — #460 / #465: stronger conventional corrective PRs

These PRs show explicit root defects, broad security/authority consequences, substantial regression proof, explicit non-goals, and merge discipline. Their closure is still primarily demonstrated through implementation tests.

### Stage B — #468 onward: semantic observability and graph-integrated closure

#468 materially expands the measurement model. Subsequent graph-integrated repairs increasingly follow this pattern:

1. identify a frozen defect/finding cluster;
2. state the governing invariant;
3. trace the real dependency/runtime path;
4. choose an authoritative repair point;
5. prove the failure at its real execution layer;
6. reconcile graph evidence;
7. require targeted findings to disappear;
8. require unrelated known findings to remain visible;
9. state non-goals to prevent overclaiming closure.

That is a different definition of `done` from ordinary fix + regression-test closure.

## Historical corrective contrast — corrected after population reconnaissance

The full-history reconnaissance already shows why local proof is not equivalent to architectural closure:

- #58 → #59;
- #107 → #108;
- #164 → #165 / #166;
- #168 → #169;
- **#369 → #370 → #371 → #372 → #373 → #374**.

The last chain was previously sampled only through #372. The population scan found that #373 explicitly reports `Codex P2 on #372`, and #374 explicitly reports `Codex P2 on #373`. The working record is therefore revised rather than preserving the earlier truncated representation.

The #369 component is particularly useful because the corrective surface contracts while semantic conditions continue to be discovered. It is a candidate case of **semantic fragmentation depth**, not merely a large-PR effect.

## PR size does not explain the apparent improvement

The graph-integrated PRs are not uniformly smaller. The stronger candidate mechanism is alignment among:

**semantic reasoning scope → actual architectural blast radius → authoritative repair point → proof scope → observable closure.**

This remains a hypothesis until population-level adjudication and outcome analysis are complete.

## #471 → #472: pre-merge interception as a distinct outcome

#471 and #472 share the same base SHA. #471 was closed unmerged after proposing a narrower/different ownership design. #472 merged a broader PostgreSQL-backed durable authority addressing the shared idempotency cluster.

The defensible observation is that the first design did not enter `main` and the broader design did. Do not attribute the redesign to the graph without contemporaneous causal evidence. Code it as pre-merge architectural broadening/design supersession until adjudicated.

This is why the study must measure defects intercepted before merge, not only downstream corrective descendants.

## #465 → #473: local closure versus governing-invariant closure

#465 strongly repairs email ownership verification semantics. The later frozen baseline still contains GF-14, showing that concurrent consumption of verification authority remained unresolved. #473 closes that concurrency property together with GF-22/GF-23 under the single-use credential invariant.

Working coding rule:

- #465 — local behavioral/security contract strongly repaired;
- GF-14 after #465 — broader state-transition/concurrency invariant still open;
- #473 — later root-level concurrency closure.

Do not code #465 as the introduction of GF-14 without source-history proof.

## Preliminary interpretation

Current evidence supports only a process/mechanism proposition:

> Post-#468 Ajenda remediation increasingly makes governing invariants, semantic scope, proof topology, residual-defect visibility, and architecture closure explicit and machine-observable.

It does **not** yet establish a treatment effect on corrective-descendant rate, cascade depth, rework, or defect incidence.

## Methodological implication

Preserve #460 as the preregistered provisional intervention boundary, but model graph capability as a time-varying vector reconstructed from contemporaneous evidence. The graph/tooling sequence #453–#459 and the semantic-hardening step at #468 are analytically important maturity changes.

For every production PR, the full-population extraction should capture:

- change/defect mechanism;
- semantic domains and boundaries;
- graph capabilities available/used;
- requested scope, predicted blast radius and actual implementation scope;
- governing invariant(s);
- authoritative repair mechanism;
- proof layers required/exercised;
- graph/finding state before and after;
- unrelated findings preserved;
- pre-merge corrections/supersession;
- causal descendants and relationship class;
- semantic dimensions discovered in later generations;
- severity/boundary movement;
- elapsed time as a secondary/censoring variable.

No composite PR-quality score is authorized at this stage.
