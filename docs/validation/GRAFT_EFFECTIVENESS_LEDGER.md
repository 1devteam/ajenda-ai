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
