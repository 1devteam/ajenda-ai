# Continuous Assurance Pass 2 — closure record

**Closure date:** 2026-10-07  
**Implementation PR:** #565  
**Merged implementation SHA:** `d90d8cdf5828a148eaf682562049117cdd92cde8`  
**Closure PR:** #566

## Exit result

Pass 2 is closed.

Continuous assurance now runs as an independent recurring process that re-reads canonical tenant mission/runtime state and persists only assurance-owned observation history. It does not create runtime work, mutate business/runtime authority, approve side effects, or rewrite epistemic policy confidence.

The merged implementation provides:

- tenant-scoped append-only assurance snapshots;
- durable findings and first-divergence history;
- task, lease, lineage, evidence, artifact/runtime-state, shadow/runtime, and semantic reconciliation reads;
- contradiction, drift, incomplete-evidence, and invalid-runtime-state findings;
- runtime-derived epistemic calibration samples without promoting those samples into execution or confidence authority;
- fingerprint deduplication so unchanged recurring scans do not inflate history or calibration;
- tenant-scoped assurance history and summary APIs;
- aggregate Prometheus assurance metrics;
- contradiction, drift, first-divergence, and tenant-scan-failure alerts;
- a dedicated recurring `assurance` service separated from the runtime worker;
- a continuous-assurance operator runbook.

## Authority boundary

The monitor's durable write boundary is limited to:

- `assurance_snapshots`;
- `assurance_metric_state`.

The assurance service deliberately avoids `MissionRepository.list_by_tenant()` because that path can reconcile review holds and mutate mission status. Mission/runtime reads are direct tenant-scoped SELECTs. Persisted assurance records declare `authority_class = "read_model"` and `grants_execution_authority = false`.

The monitor does not create, queue, claim, start, retry, cancel, or complete tasks and does not mutate missions, leases, business profiles, knowledge, credentials, approvals, providers, or external side effects.

## Tenant proof

The real Postgres integration proof verifies assurance history under a non-bypass PostgreSQL role rather than the Testcontainers database owner, which bypasses RLS. The proof confirms same-tenant visibility and cross-tenant invisibility for `assurance_snapshots`.

## Restart/resume proof

The Pass 2 closure proof exercises the recurring `run_once` path across separate assurance runtime instances backed by the same committed Postgres state.

It proves:

1. the first assurance process persists one durable observation;
2. a restarted assurance process reuses that durable observation when runtime truth is unchanged;
3. restart does not append a duplicate observation or duplicate calibration sample;
4. when runtime-owned mission state changes independently, a later restarted assurance process appends a new historical observation;
5. the prior observation remains preserved;
6. assurance does not rewrite the mission status or mission metadata while observing either state.

This establishes restart/resume behavior from durable database truth rather than process memory.

## Live and CI proof

The #565 implementation head passed all required repository proof lanes before merge:

- CI — Pull Request Gate;
- Pre-Merge Live Runtime Proof;
- Recovery Hardening Validation;
- Security — Vulnerability Scanning;
- Architecture — Canonical Dependency Graph;
- Architecture — PR Invariant Classifier;
- Architecture — Selective Proof Shadow;
- Architecture — GRAFT Runtime Contract Adjudication.

The live runtime proof starts the independent assurance service, executes a worker-backed operator mission proof, runs a one-shot assurance cycle against persisted runtime evidence, verifies assurance metrics at the API surface, and verifies the Prometheus scrape target.

The closure PR adds the dedicated restart/resume integration proof required to close the remaining Pass 2 evidence gap. Its full integration lane passed 266 tests with 2 credential-gated provider tests skipped.

## Epistemic calibration boundary

Pass 2 closes the calibration-source requirement, not a statistical calibration maturity claim.

Eligible terminal mission observations persist:

- the observed epistemic confidence;
- whether the sample is calibration-eligible;
- whether the observed runtime/reconciliation outcome aligned.

These samples remain evidence. They do not rewrite policy confidence. Statistical calibration quality requires accumulated eligible production/runtime samples over time and remains an operational measurement concern rather than a reason to keep Pass 2 implementation open.

## G.R.A.F.T. reconciliation

G.R.A.F.T. materially affected Pass 2 implementation before code was written by exposing the hidden mutation in `MissionRepository.list_by_tenant()`. That prevented the assurance monitor from inheriting runtime mutation authority.

During #565, G.R.A.F.T./CI also identified:

- a missing migration-contract proof;
- a repeated-observation unit-fixture defect;
- stale migration-head assertions;
- ordinary lint/import-order hygiene;
- incomplete graph mapping for several assurance, deployment, migration, and documentation surfaces.

For this closure change, the predicted blast radius was intentionally narrow:

- assurance integration proof;
- Pass 2 roadmap state;
- Pass 2 validation documentation;
- G.R.A.F.T. effectiveness documentation.

No runtime authority, provider, credential, queue, worker execution, business-state, onboarding, billing, or UI behavior is intended to change.

The closure G.R.A.F.T. run reported graph SHA-256 `886520e59825a98f1e569618dd39ac162320eb574acef3155c88b50fd7143fc3`, zero affected semantic nodes, zero upstream consumers, zero downstream dependencies, zero relevant invariants, and three unmapped changed files. All three unmapped files are documentation surfaces: the completion roadmap, this closure record, and the G.R.A.F.T. effectiveness ledger. The changed assurance integration test was not reported as unmapped.

That actual result matches the predicted authority boundary: no production runtime behavior changed. The lack of semantic graph impact is therefore supported by the test/documentation-only diff, while the three unmapped documentation files remain explicit G.R.A.F.T. representation gaps rather than permission to infer zero architectural significance.

## Deferred beyond Pass 2

The following remain outside Pass 2:

- statistical calibration maturity from a larger accumulated sample set;
- provider capacity discovery;
- internal CRM customer-value completion;
- external provider lanes;
- SaaS/onboarding product completion;
- presentation/UI completion;
- production operations completion.

Those are owned by Passes 3–7 or ongoing operations.

## Completion statement

Pass 2 is complete once #566's final required repository checks are green and the PR is merged.

The restart/resume proof itself is green in the full integration lane. After merge, Ajenda has a tenant-safe, durable, recurring, read-only assurance layer that can independently detect incomplete evidence, drift, contradiction, first divergence, and calibration observations without manufacturing runtime authority.
