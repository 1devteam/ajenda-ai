# Runtime Evidence Substrate — G.R.A.F.T.+ Impact Evidence

Baseline commit: `634735e4a23f7ae7cd0755e12592ccc9830ba410`  
Implementation commit: `ae415ece`

Commands run:

```bash
python scripts/validation/build_dependency_graph.py
python scripts/validation/graph_impact_analysis.py \
  --changed-file backend/services/runtime_evidence_ledger.py \
  --changed-file backend/services/runtime_evidence_consumers.py \
  --changed-file backend/services/continuous_assurance.py \
  --changed-file backend/services/mission_runtime_evidence_projection.py \
  --changed-file backend/services/execution_coordinator.py \
  --changed-file backend/services/worker_runtime_service.py \
  --changed-file backend/services/mission_composition/confirmation_phase.py \
  --changed-file tests/unit/services/test_runtime_evidence_ledger.py \
  --changed-file tests/integration/runtime/test_dispatcher_audit_events_real.py \
  --json --output /tmp/runtime-evidence-graft-impact.json
python scripts/validation/graph_proof_selection.py \
  --impact-report /tmp/runtime-evidence-graft-impact.json \
  --json --output /tmp/runtime-evidence-graft-proof.json
python scripts/validation/graft_plus_gate.py --base-ref origin/main --head-ref HEAD
```

Observed impact: 9 changed files, 34 graph nodes, 114 selected tests, 9
relevant invariants, and zero unmapped changed files. The graph selected the
API and worker runtimes, tenant DB/RLS boundary, queue/lease worker spine,
and runtime/side-effect proof bundles. The graph also reported pre-existing
manual review items for governed egress and tenant isolation; this change does
not expand either surface.

The raw JSON evidence is generated at `/tmp/runtime-evidence-graft-impact.json`
and `/tmp/runtime-evidence-graft-proof.json` during validation to avoid
committing a volatile generated graph artifact.
