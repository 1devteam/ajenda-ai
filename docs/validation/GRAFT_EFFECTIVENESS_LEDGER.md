# G.R.A.F.T. effectiveness ledger

This ledger records where G.R.A.F.T./G.R.A.F.T.+ materially helps implementation and where its
representation or proof selection creates friction or blind spots. It is evidence for the R&D
program as well as an Ajenda engineering record.

## 2026-10-06 — Pass 1 semantic-goal reconciliation (#562)

**Helped**

- Pre-code tracing kept the change inside the read-model/intelligence boundary and avoided queue,
  lease, provider, credential, migration, onboarding, and UI authority changes.
- The graph expanded proof obligations far beyond the small implementation diff, exposing a broad
  consumer/dependency surface that required repository-level proof.
- G.R.A.F.T./CI/live runtime proof all passed after implementation.

**Hindered / over-selected**

- Risk classification included `external-egress` when the actual semantic-goal change introduced
  no network/provider egress. This appeared to be coarse file-level classification from a shared
  action module rather than true behavioral egress risk.
- This increased proof/review load without identifying a corresponding implementation defect.

**Result**

Useful for coordinating proof and preserving authority boundaries, but risk-domain precision can be
improved.

## 2026-10-06 — Pass 1 worker-backed adversarial closure (#564)

**Helped**

- The workflow forced static impact and runtime evidence to be considered together.
- The live proof confirmed zero runtime contradictions, no first divergence, aligned shadow/runtime
  state, aligned semantic state, fail-closed coverage, and tenant isolation.

**Hindered / graph gap**

- The only changed file, `deploy/scripts/operator-mission-proof.py`, was unmapped.
- The graph therefore reported zero upstream consumers, zero downstream dependencies, and zero
  relevant invariants even though the script exercises several architectural boundaries.
- Treating the graph result alone as blast radius would have materially understated the proof
  surface.

**Result**

Runtime joining was valuable; canonical mapping of validation/operator proof surfaces is incomplete.

## 2026-10-06 — Pass 2 pre-code authority tracing

**Helped**

- G.R.A.F.T. workflow/source-of-truth review exposed that
  `MissionRepository.list_by_tenant()` is not a pure read: it can reconcile review holds and mutate
  mission status.
- Reusing that repository method inside continuous assurance would have violated the Pass 2 invariant
  that the monitor cannot mutate runtime/business state.
- The Pass 2 assurance service therefore uses direct tenant-scoped SELECTs and writes only to its own
  assurance history.

**Result**

This is a concrete avoided implementation defect: architectural tracing changed the implementation
choice before code crossed the wrong authority boundary.

## 2026-10-06 — Pass 2 PR proof failures (#565)

**Helped**

- The PR invariant classifier correctly rejected the migration because the changed surface lacked a
  migration-contract proof under `tests/unit/db/`. That was a real evidence obligation, not a
  product-runtime defect.
- Graph-selected proof executed enough of the affected unit surface to expose the repeated-observation
  fixture defect in `test_unchanged_observation_reuses_latest_snapshot` before merge.
- The failure separated a test-harness assumption from service behavior: one reconciliation performs
  four scalar reads when there are no tasks, so a second reconciliation required eight mocked scalar
  results.
- Reviewing the migration proof requirement also exposed stale current-head assertions in existing
  migration contract tests before full CI reached them; those were advanced to
  `0049_continuous_assurance` in the same coherence repair.

**Hindered / graph gap**

- The impact report listed 12 unmapped changed files. Those files cannot contribute normal
  upstream/downstream graph evidence, so the reported blast radius is incomplete until those
  deployment, documentation, migration, or assurance surfaces are modeled.
- The lint failure was ordinary import-order hygiene and added no architectural information.

**Result**

G.R.A.F.T. materially improved first-pass closure by catching one missing proof obligation and one
test-fixture defect, but unmapped-file coverage remains a measurable representation gap. The repair
did not require changing Pass 2 runtime authority or assurance semantics.



## 2026-10-07 — Pass 2 closure proof

**Predicted blast radius**

- assurance integration proof only;
- Pass 2 roadmap/closure documentation;
- no runtime-authority, provider, credential, queue, worker-execution, onboarding, billing, or UI behavior changes.

**Closure criterion**

The graph-selected and repository-required proof should confirm that restart/resume behavior depends on durable assurance history rather than process memory, while preserving the existing read-only authority boundary. Any graph expansion beyond the changed assurance proof and documentation surfaces should be treated as evidence to inspect, not silently dismissed.

**Result**

Pending closure-PR proof. This entry must be finalized with the actual G.R.A.F.T./CI result before merge.
