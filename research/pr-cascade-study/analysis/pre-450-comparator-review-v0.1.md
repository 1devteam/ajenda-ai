# Pre-#450 Comparator Review v0.1

**Status:** exploratory comparator evidence; not a population finding  
**Frozen post-period reference:** Ajenda `main` at `9a3a3009217d0ea564bd0a04086330a5bc491db5`  
**Purpose:** establish source-backed pre-#450 examples that include both planned slicing and genuine corrective propagation  
**Selection caution:** these cases are calibration/comparator cases, not a representative sample of all pre-#450 PRs.

## 1. Why this comparator document exists

A before/after study can become biased if the pre-period is represented only by memorable corrective cascades while the later period is represented by carefully selected successful repairs. This document therefore preserves several qualitatively different pre-#450 cases:

- late-review follow-up on a focused hardening PR;
- diagnostic correctness correction;
- planned multi-slice architecture work;
- an omitted tenant-isolation surface after a planned RLS foundation;
- a policy-ordering defect after a compliance foundation;
- a deep multi-generation corrective chain in outreach/send behavior.

The purpose is not to label the pre-period as low quality. It is to provide calibrated relationship types for later population coding.

## 2. Comparator relationship classes used here

### Planned dependency / staged construction

The parent explicitly announces that another boundary is deferred to a later PR. A child implementing that announced boundary should not be counted as corrective rework merely because it immediately follows the parent.

### Direct corrective descendant

The child explicitly states that behavior in the parent was incorrect, incomplete, unsafe, or ineffective and changes that behavior.

### Late-review correction

The child explicitly attributes the correction to review feedback received after the parent was merged or otherwise finalized.

### Diagnostic correction

The child repairs instrumentation/observability logic rather than changing the underlying runtime state-machine behavior.

### Semantic-fragmentation chain

Successive corrective descendants expose additional semantic conditions in the same behavior/boundary after earlier fixes have merged. This is a candidate process pattern, not an automatic quality score.

## 3. PR #58 → #59: focused hardening followed by late-review correction

### PR #58 — `harden(worker): validate handler output contract`

Repository-observable scope:

- canonical handler-result validation before dispatcher completion;
- JSON-object/string-key requirements;
- non-empty `handler` and `status` fields;
- status restricted to `completed`, `failed`, or `blocked`;
- rejection of non-JSON-serializable result payloads before lineage persistence;
- focused unit coverage plus runtime integration validation commands.

Lifecycle metadata records two commits, two changed files, 86 additions, and four deletions.

This is important as a baseline control because it is already small, contract-oriented, and test-conscious. Chronology alone cannot support a narrative that earlier development lacked discipline.

### PR #59 — `fix(worker): restrict handler output contract to completion`

The PR body explicitly says it adds regression tests for **late Codex feedback from PR #58**.

It changes two semantic decisions from #58:

1. restrict accepted status to `completed` while dispatcher completion is the only supported success path;
2. apply JSON-serializability validation only to outputs that are actually persisted, preserving transient non-persisted payloads.

### Working relation

`#58 -> #59 = direct late-review corrective descendant`, high textual confidence.

### Study value

This is not a broad architectural cascade. It is a compact example where a focused contract-hardening PR still receives a narrow semantic correction immediately afterward. It can be used to distinguish review-timing effects from architectural blast-radius mismatch.

## 4. PR #107 → #108: observability feature whose diagnostic check was semantically ordered incorrectly

### PR #107 — claim/start mismatch diagnostics

The PR adds `mismatched_state_count` and attempts to surface a `CLAIMED task + ACTIVE lease` mismatch. It explicitly states that recovery behavior and queue behavior are unchanged; this is diagnostics only.

### PR #108 — preserve original recovery states for diagnostics

The child explicitly states the problem in #107: the code checked `lease.status` **after** transitioning the lease to `EXPIRED`, so the diagnostic could not accurately observe the intended original mismatch.

The correction snapshots original task/lease states before mutation and uses them for diagnostics and logs, again without changing recovery state-machine behavior.

### Working relation

`#107 -> #108 = direct diagnostic corrective descendant`, high textual confidence.

### Study value

This is useful because the defect is not a missing broad subsystem. It is an ordering/observation error inside a narrow diagnostic feature. A graph may or may not be expected to help with this class; grouping all corrections under “blast-radius failure” would overstate the hypothesis.

## 5. PR #164 → #165 / #166: planned architecture slice plus genuine omission

This cluster is particularly useful because it contains both planned follow-up and corrective propagation.

### PR #164 — tenant-scoped session foundation

The PR adds:

- tenant-scoped DB session primitive;
- `SET LOCAL app.current_tenant_id` context;
- request tenant helpers;
- tenant DB dependency;
- RLS migration for tenant-scoped tables.

Its scope boundary explicitly says tenant-facing routes are **not migrated yet** and that route migration belongs in the **next clean slice**.

### PR #165 — route migration

The PR explicitly says #164 added RLS/session primitives and this PR closes the announced follow-up blocker by moving tenant-facing routes to the tenant-scoped dependency.

### Working relation #164→#165

`planned_dependency`, not corrective by default.

Counting #165 as rework would incorrectly penalize an intentionally staged architecture rollout.

### PR #166 — include `audit_events` in tenant RLS policy

The PR explicitly states that `audit_events` has `tenant_id`, is tenant-scoped, and was left outside the RLS policy, creating a tenant-isolation gap **after PR #164**.

### Working relation #164→#166

`direct corrective descendant`, high textual confidence.

### Study value

The same parent can have both:

- an intentionally deferred downstream slice (#165), and
- an actual omitted boundary (#166).

This is a strong argument for relation-level adjudication instead of PR adjacency or simple descendant counts.

It also provides an architectural comparator for later #469: both concern RLS plus application/session interaction, but the repository and measurement environment differ materially.

## 6. PR #168 → #169: policy-ordering correction after a scoped foundation

### PR #168 — compliance foundation

Adds compliance enums/fields, migration, PolicyGuardian compliance evaluation, and focused tests. Its non-goals exclude JWT/IdentityService/API-key/tenant-middleware work from the earlier source PR.

### PR #169 — enforce marketing policy before jurisdiction exits

The child explicitly says #168 allowed marketing workflows under jurisdiction-specific paths to bypass the marketing opt-out check because jurisdiction evaluation returned early.

The fix changes policy ordering and adds a targeted regression for an EU marketing workflow without opt-out mechanism.

### Working relation

`#168 -> #169 = direct corrective descendant`, high textual confidence.

### Study value

This is a semantic control-flow error rather than a missing dependency or omitted table. It should be coded by defect mechanism so later graph-assisted cases are compared to relevant failure classes.

## 7. PR #369 → #374: deep corrective propagation in ability world-state / external-send chain

This is currently the strongest verified pre-#450 semantic-fragmentation comparator.

### 7.1 PR #369 — world-state depth for composition outreach chain

The PR states that composition selected the right ability sequence but froze intent stubs and ran independent `tool.invoke` tasks. It adds:

- `prospect_candidates` production;
- qualify/enrich consumption and output artifacts;
- lease-scoped upstream-output binding;
- claim deferral for incomplete dependency keys;
- draft personalization from bound prospect state.

The PR explicitly excludes real third-party email enrichment providers, N-way draft fan-out, and UI redesign.

Lifecycle metadata: one commit, 13 changed files, 1,156 additions, 63 deletions.

### 7.2 PR #370 — four corrections explicitly attributed to review on #369

The body says: `Follow-up for Codex review on #369.`

It lists four findings:

1. bridge adapter was provisioned `read_only` while composed `web.research` could require `external_read`;
2. `gtm.email_send` received a forbidden extra `prospects` field;
3. qualify binding could overwrite richer enriched contacts;
4. empty internal research incorrectly set `real=false`, leading to `candidates_real` handling.

This is already broader than a one-line bug fix: one parent generated corrections across side-effect classification, action input shape, data merge semantics, and truth-state semantics.

### 7.3 PR #371 — send binding via `introduction_drafts`

The body explicitly says it addresses a Codex P2 on #370: introduction drafts land under context while root prospects remain empty, so the send binding gate fails.

The correction specializes `gtm.email_send` binding from introduction drafts and changes the send binding gate.

### 7.4 PR #372 — placeholders must not unlock external send

The body says `Codex P1 on #371`: draft world-state containing `pending.binding@invalid.local` must not unlock external send.

The correction requires a deliverable recipient and makes placeholders fail closed.

### 7.5 PR #373 — reserved TLD rejection

The body says `Codex P2 on #372`: reject reserved `.example`, `.test`, and `.local` placeholders before external send.

### 7.6 PR #374 — single-label reserved-domain rejection

The body says `Codex P2 on #373`: add exact-domain rejection for `test`, `local`, and `localhost` before `gtm.email_send`.

### Working chain

The textual parentage is unusually explicit:

`#369 -> #370 -> #371 -> #372 -> #373 -> #374`

Each later body directly names the immediately preceding review/finding. This supports high-confidence candidate corrective edges before diff-level adjudication.

### Why this is called semantic fragmentation rather than simply “a large bad PR”

The corrective surface becomes progressively smaller while newly specified semantic conditions continue to appear:

- side-effect level;
- action input contract;
- data merge identity/richness;
- truth-state semantics;
- artifact-to-send binding;
- placeholder-recipient validity;
- reserved-TLD validity;
- reserved single-label domain validity.

The key candidate phenomenon is not raw file count. It is **successive discovery of semantic preconditions in one runtime/external-effect path after prior corrections merged**.

### Alternative explanations to retain

- review was occurring serially after merge rather than before merge;
- the feature introduced genuinely new complexity that was hard to test exhaustively;
- the test suite/provider fixtures at that time may not have represented all recipient/domain cases;
- the LLM/reviewer may have generated one finding at a time regardless of architectural understanding;
- a graph could still fail to prevent this class if recipient-domain validity is not represented in graph semantics;
- the chain may partly reflect very fast merge cadence rather than a stable production exposure period.

The chain is therefore a comparator, not proof that graph tooling would have prevented it.

## 8. Comparison dimensions suggested by these controls

The pre-#450 controls show that a useful analysis must distinguish at least:

1. **planned next slice vs corrective child** — #164→#165 versus #164→#166;
2. **narrow local semantic correction** — #58→#59;
3. **diagnostic correctness** — #107→#108;
4. **policy-order/control-flow correction** — #168→#169;
5. **multi-generation cross-contract fragmentation** — #369→#374.

A later graph-assisted PR should be compared with a relevant defect mechanism rather than with the most dramatic historical case by default.

## 9. Candidate before/after variables grounded in these cases

### Root-defect completeness

Did the parent identify the governing defect mechanism, or did later children reveal additional independent conditions that should plausibly have been in the same reasoning scope?

### Semantic fragmentation depth

How many generations were required before the same runtime/authority/effect path stopped producing explicitly linked corrective children?

### Boundary movement

Did children remain inside one function/module, or move across authority, persistence, runtime, provider, tenancy, and external-effect boundaries?

### Planned-dependency ratio

What fraction of immediate same-subsystem PRs were explicitly preplanned versus corrective?

### Review timing

Were findings intercepted before merge, during review after merge, or by runtime use later?

### Proof topology

Was the relevant failure mode represented by the parent’s proof? For example, unit structure proof may not cover real concurrency or an external-effect placeholder validity boundary.

### Residual-defect visibility

Did the parent state what remained intentionally unresolved, making later work expected rather than surprising?

## 10. Controls against directional bias

To avoid constructing a favorable post-graph comparison, subsequent baseline work must add:

- pre-#450 PRs with no known corrective descendants;
- large pre-#450 PRs that closed broad scope successfully;
- small pre-#450 PRs that still cascaded;
- post-#460 PRs that do generate corrective descendants;
- graph-guided PRs where graph outputs were incomplete or wrong;
- feature-evolution sequences comparable to #484–#496;
- closed-unmerged pre-graph designs if available;
- review-model and CI-state metadata where reconstructable.

## 11. Current neutral synthesis

These comparator cases establish that the pre-#450 period contains both disciplined planned decomposition and clear corrective propagation. The #369–#374 sequence is a strong high-confidence cascade candidate, but it must not be treated as representative of the entire baseline.

The most important methodological conclusion from this review is not that one era is better. It is that **the unit of causal coding must be the relationship and semantic mechanism, not the PR number sequence**.

## 12. Next source work

1. Expand from calibration cases into a frozen pre-#450 population sample or full census.
2. For #58/#59, #107/#108, #164/#166, #168/#169, and #369–#374, inspect diffs, comments/reviews, test changes, and source ancestry.
3. Identify matched later cases by defect mechanism rather than by size alone.
4. Record review timing and whether the correction was discoverable by then-available tests/graph semantics.
5. Preserve cases where the graph would not reasonably be expected to help; these are necessary controls for graph-specific claims.
