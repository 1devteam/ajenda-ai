# Preliminary PR Quality Analysis — PR #460 onward

**Status:** exploratory analysis note; not an empirical finding  
**Analysis snapshot:** through PR #473  
**Population use:** prospective/process evidence; downstream elapsed-time windows are censoring controls, not the primary definition of quality

## Question

Do Ajenda PRs from the provisional graph-assisted period show a measurable change in PR quality compared with earlier corrective work, and if so, what changed?

This note does **not** equate PR quality with PR size, commit count, prose length, CI success, or absence of a later PR within an arbitrary number of days. It separates immediately observable engineering/process evidence from realized downstream outcomes.

A companion analysis, `multivariate-pr-quality-framework-v0.1.md`, expands the model across defect mechanism, semantic scope, boundary crossing, invariant coverage, repair-cluster coherence, proof topology, pre-merge interception, residual-defect visibility, corrective propagation topology, and graph maturity.

## Quality dimensions used for this preliminary review

1. **Root-defect clarity** — whether the PR identifies the actual defect mechanism rather than only the symptom.
2. **Blast-radius reasoning** — whether dependencies, affected runtime paths, boundaries, or connected contracts are explicitly traced.
3. **Invariant / architecture contract** — whether the PR states the system property that must hold after repair.
4. **Scope discipline** — whether non-goals and unrelated known defects remain explicit rather than being silently absorbed or claimed closed.
5. **Proof quality** — whether proof includes adversarial, integration, concurrency, cross-boundary, or fail-closed tests appropriate to the defect.
6. **Architectural closure evidence** — whether the repair is reconciled against the canonical graph/invariant model and the targeted architectural finding disappears without erasing unrelated findings.
7. **Pre-merge interception / design supersession** — whether material defects or weaker designs are corrected before reaching `main`.
8. **Realized outcome quality** — later corrective descendants, cascade depth, semantic fragmentation, time to closure, severity movement, and rework.

The first seven dimensions can be observed contemporaneously. The eighth requires later causal evidence but must not be reduced to a single elapsed-time cutoff.

## Cohort handling

### Included production / architecture-process evidence

- #460 — authority-containment correction
- #465 — password-signup verification correction
- #468 — semantic graph hardening; instrumentation intervention
- #469 — RLS/session-boundary correction
- #470 — post-RLS graph certification
- #471 — closed-unmerged idempotency repair attempt; retained as process evidence only
- #472 — durable HTTP idempotency repair
- #473 — atomic single-use credential-transition repair

### Excluded from product-quality comparison

- #461–#464 — Dependabot maintenance PRs; unlike change class
- #466 — research instrumentation/documentation; excluded by protocol
- #467 — invalid prospective pilot / protocol execution error; excluded from treatment-effect analysis

## PR-level assessment

| PR | Root defect | Blast radius | Invariant | Proof | Graph closure | Scope discipline | Preliminary assessment |
|---|---|---|---|---|---|---|---|
| #460 | Strong | Moderate | Moderate | Strong | Not present | Strong | Major improvement in defect description, authorization boundaries, negative scope, and regression proof, but still primarily a conventional multi-surface corrective package rather than machine-reconciled architectural closure. |
| #465 | Strong | Moderate | Moderate | Strong | Not present | Strong | Strong local-contract repair. However, the post-#465 baseline still contained GF-14 verification-token concurrency. This supports incomplete closure of the broader single-use credential-transition invariant, not a claim that #465 introduced that defect. |
| #468 | Strong | Strong | Strong | Strong | Instrumentation itself | Strong | Qualitative intervention in the evidence model. It explicitly represents RLS, egress, and state-ownership/concurrency blind spots and prevents acknowledged defects from being mistaken for repaired defects. |
| #469 | Strong | Strong | Strong | Strong | Strong | Strong | First clear example in this sequence of graph-integrated remediation: migration + runtime session repair are derived from the blast radius, PostgreSQL behavior is tested directly, and graph semantics must show the repaired tables as RLS-complete. |
| #470 | N/A runtime | Strong | Strong | Strong | Strong | Strong | Closure/provenance PR. It distinguishes an intentional pre-tenant control-plane exception from an unexplained RLS gap while requiring repaired and still-open findings to remain correctly classified. |
| #471 | Strong | Strong | Strong | Strong planned | Not realized | Strong | Closed unmerged. It targeted GF-13/GF-27 with Redis ownership while leaving GF-25/GF-26/GF-28 separate. Because it never merged, it is process evidence rather than production outcome evidence. |
| #472 | Strong | Strong | Strong | Very strong | Very strong | Very strong | Root-cause cluster repair rather than independent cache patches. It unifies GF-13/GF-25/GF-26/GF-27 and adjudicates GF-28 under one operation-identity/ownership model, includes 8-way PostgreSQL contention proof, encrypted replay proof, abandoned-claim recovery, and a graph closure ratchet that removes only the targeted finding. |
| #473 | Strong | Strong | Very strong | Very strong | Very strong | Very strong | Shared-invariant repair across three credential transitions. It reuses existing durable rows as transaction ownership rather than adding parallel coordination, proves exactly-one successor under real PostgreSQL contention, and requires the graph to move three findings from violation to enforced while preserving unrelated defects. |

## Observed quality transition

The evidence suggests **two distinct stages**, not one simple before/after switch at #460.

### Stage A — #460 / #465: stronger conventional corrective PRs

These PRs are materially better specified than many earlier Ajenda corrections:

- explicit root defects;
- explicit security/authority consequences;
- extensive regression proof;
- explicit non-goals;
- deliberate merge discipline.

But they still prove closure mainly through implementation tests. They do not yet require the architecture model to show that the targeted invariant is restored while unrelated defects remain visible.

### Stage B — #468 onward: graph-integrated architectural closure

#468 is a maturity point because it explicitly hardens the graph against known blind spots in RLS, egress, and concurrency/state ownership. After that point, #469, #472, and #473 use a stronger repair pattern:

1. identify frozen defect IDs / semantic findings;
2. identify the shared architectural invariant;
3. trace the actual dependency/runtime path;
4. choose a root-level repair mechanism;
5. add proof at the failure mode's real level (PostgreSQL/RLS/concurrency, not only unit mocks);
6. update the canonical graph evidence;
7. require the targeted finding to disappear;
8. require unrelated known findings to remain visible;
9. state explicit non-goals so closure cannot be overclaimed.

That is a qualitatively different definition of "done" from earlier fix + regression-test PRs.

## Important contrast with historical corrective cascades

Earlier Ajenda history contains direct fix-the-fix / incomplete-blast-radius chains such as:

- #58 → #59
- #107 → #108
- #164 → #165 / #166
- #168 → #169
- #369 → #370 → #371 → #372

Those sequences show that passing local proof did not always imply architectural closure. The companion multivariate analysis also shows why **file breadth alone is not sufficient**: #58/#59 and #107/#108 remain within the same tiny file surface, while the defect mechanism is semantic contract/state-ordering mismatch.

This is process and mechanism evidence, not yet proof that graph assistance reduces downstream cascades.

## PR size does not explain the apparent improvement

The graph-integrated PRs are not uniformly smaller:

- #460: 27 files, 28 commits, +825 / -87
- #465: 24 files, 34 commits, +838 / -572
- #468: 13 files, 21 commits, +1097 / -400
- #469: 21 files, 23 commits, +345 / -21
- #471: 6 files, 8 commits, +447 / -123, unmerged
- #472: 23 files, 17 commits, +1139 / -216
- #473: 11 files, 13 commits, +533 / -34

The observed difference is therefore not "smaller PRs are better." The stronger candidate explanation is **better alignment among semantic reasoning scope, actual architectural blast radius, authoritative repair point, and proof scope**. This remains a hypothesis.

## #471 → #472 as process evidence

#471 and #472 share the same base SHA. #471 was closed unmerged after proposing Redis-backed ownership for GF-13/GF-27 while explicitly deferring GF-25/GF-26/GF-28. #472 instead merged a PostgreSQL-backed durable authority that treats the broader idempotency cluster as one architectural problem.

The observable fact is that the narrower/different design did **not** enter `main`; the broader root-cause package did. This is potentially important evidence of improved pre-merge correction quality. The reason for the redesign must not be attributed to the graph unless contemporaneous review/task evidence explicitly supports that causal claim.

This is why the study must count **pre-merge interception and design supersession**, not only post-merge corrective descendants.

## #465 → #473 as incomplete-closure evidence

#465 strongly repaired password signup and email verification semantics, but the later frozen baseline still identified GF-14: concurrent verification could consume the same authority before successor bootstrap authority was safely serialized. #473 repairs that concurrency property together with GF-22 and GF-23 under one single-use credential invariant.

This should currently be coded as:

- #465: strong local behavioral/security correction;
- GF-14 after #465: broader state-transition invariant remained incomplete;
- #473: later root-level concurrency closure.

Do **not** code this as "#465 introduced GF-14" without source history proving introduction.

## Preliminary interpretation

The strongest current evidence is that PR quality has changed in **architecture reasoning, invariant clustering, proof topology, negative-evidence preservation, and closure observability**, especially after #468.

What is **not** yet established:

- lower corrective-descendant rate;
- lower cascade depth;
- lower rework ratio;
- statistically significant improvement attributable to graph assistance.

Elapsed observation time is one limitation, but it is not the analytical center. Other variables can be measured now and should be included in the study.

## Methodological implication

For the prospective analysis, a single binary `pre/post #460` treatment variable is insufficient. Preserve #460 as the preregistered provisional boundary, but also code graph maturity as a time-varying vector. At minimum distinguish:

- initial graph-assisted correction period (#460 onward);
- semantic-enforcement maturity (#468 onward);
- graph-integrated remediation with explicit finding closure (#469 onward).

Any final intervention refinement must be justified from contemporaneous implementation evidence, not from favorable outcome metrics.

## Next reproducible measurement

For every prospective production PR, capture at least:

- defect/change mechanism;
- requested/change scope;
- semantic domains and boundaries implicated;
- graph capabilities available and actually used;
- graph-predicted blast radius;
- actual implementation scope;
- governing invariant(s);
- repair mechanism / authoritative control point;
- proof layers selected and exercised;
- graph findings before/after;
- targeted findings closed;
- unrelated findings preserved;
- review-discovered corrections before merge;
- merged vs superseded/abandoned;
- corrective descendants and causal class;
- semantic dimensions discovered in later generations;
- severity movement;
- elapsed time to later correction as a censoring/secondary outcome variable.

Fixed 7/14/30/60-day windows can then be used for sensitivity and right-censoring, but they are **secondary controls inside a multivariate analysis**, not the pillar of the study.