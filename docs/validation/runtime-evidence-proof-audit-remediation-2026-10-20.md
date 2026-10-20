# Runtime-evidence proof audit remediation

## Scope and source of truth

This change follows the implementation path from `MissionIntent` through the
research action-input compiler, `web.research`, the existing audit-event
ledger, and the read-only mission runtime-evidence projection. Source and
tests are the source of truth; G.R.A.F.T.+ impact/proof artifacts are used to
select verification, not to certify the implementation.

## UPG/LAP record

- **Responsibility:** preserve the explicit public-web-only source constraint,
  record composition and runtime-admission decisions at their producers, and
  export those facts with stable correlation identifiers.
- **Dependencies:** `intent_interpreter.py`, `action_input_research.py`,
  `standalone_actions.py`, `proposal_phase.py`, `mission.py`,
  `runtime_evidence_ledger.py`, and
  `mission_runtime_evidence_projection.py`.
- **Pitfalls:** accidental internal/CRM reads; a tenant-wide audit scan
  attaching another proposal's observations; legacy records falsely reported
  as contract failures; fixture proof artifacts overwritten or self-hashed;
  an observer failure changing admission authority.
- **Invariants:** no new execution authority, queue path, or database schema;
  tenant isolation and lease ownership remain unchanged; public-only work
  performs no internal-record or CRM read; observations are best-effort and
  cannot admit work; legacy evidence remains distinguishable from current
  evidence gaps.
- **Proof:** focused source-policy, composition-observation, projection
  correlation, artifact-integrity, deployment-contract, lint, format, mypy,
  G.R.A.F.T.+ reconciliation, and public-API fixture proof checks.

## Corrected audit findings

1. Aggregate proof results now have a run-scoped artifact format with each
   lane's runtime-evidence and sealed reconciliation-export filenames and
   SHA-256 digests. The aggregate SHA-256 covers the payload before its
   integrity declaration, avoiding a self-referential digest. The suite
   refuses a lane when either export's `mission_id` differs from the
   public-API proof summary.
   Isolated signup lanes use distinct RFC 2544 benchmark client identities per
   run, exercising the existing reverse-proxy identity path without changing
   signup-rate policy or reusing an exhausted test bucket.
2. The projection now exposes `tenant_id`, `mission_id`, `proposal_id`,
   `task_id`, `lease_id`, `execution_path`, and contract version wherever the
   persisted envelope supports them. A proposal identity can be recovered
   from `mission_composition.confirmed`; unrelated tenant/proposal events stay
   excluded.
3. Composition now emits producer-owned semantic-resolution and
   source-eligibility facts, in addition to interpretation, planner,
   capability, and constraint facts. Runtime admission emits a graph-admission
   fact after its normal validation and persistence path.
4. An explicit `public_web_only` intent constraint reaches `web.research` as
   `exclude_internal_records`. The handler then skips both the tenant record
   store and CRM adapter, rather than mixing their candidates with public
   search output.

## G.R.A.F.T.+ mapping and scope boundary

The explicit changed-file impact analysis selected unit, integration, and
live-runtime proof for this work. It reports two unmapped changed paths:

- `deploy/scripts/operator-mission-proof.py` is a test-only public-API proof
  orchestrator. Its request-header behavior is covered by the deployment
  contract test, but it remains a canonical graph-mapping gap to address
  separately.
- This validation document is explanatory material and has no runtime
  authority.

Neither exception is treated as graph coverage of the corresponding runtime
behavior; the source paths and their direct tests remain the proof source.

## Limits and non-goals

- Fixture proof is intentional simulated data and is labelled as such. It does
  not establish DuckDuckGo transport, external-provider, CRM, or email
  behavior.
- `scripts/validation/api_mission_proof_suite.py --mode live-provider` is
  gated by `AJENDA_API_PROOF_ALLOW_LIVE_PROVIDER=1` and an explicit live
  instruction. It is not run until an operator supplies the required provider
  configuration and approves the external read.
- Rejected admission attempts remain HTTP failure behavior; this increment
  records accepted graph admission without changing failure transaction
  semantics.

## Verification record

The following checks passed against the completed working tree:

- focused source-policy, composition-observation, projection-correlation,
  proof-artifact, and deployment-contract tests;
- `ruff check backend/ tests/ scripts/validation/`, `ruff format --check
  backend/ tests/ scripts/validation/`, and `mypy backend/`;
- all required contract, authority, migration-seed, ability-rollout, G.R.A.F.T.
  reconciliation, and G.R.A.F.T. drift checks;
- the full non-integration aggregate: 3,292 passed, 1 deselected;
- real PostgreSQL HVAC execution, runtime-reconciliation, graph-admission, and
  tenant-isolation integration proofs: 21 passed;
- a ten-lane public-API fixture proof. Each lane had matching mission identity
  in its runtime-evidence and canonical reconciliation export; all ten exports
  passed independent G.R.A.F.T. reconciliation.

The aggregate test run emits one existing `GRAFT_AMBIGUOUS_CANDIDATES` warning
for package-affinity ambiguity. It is neither suppressed nor treated as proof
of runtime correctness.

Proof artifacts are written under a run-specific temporary output directory
and deliberately are not committed: they contain runtime identifiers and are
reproducible with `scripts/validation/api_mission_proof_suite.py`. No live
provider proof was performed: it remains explicitly operator-authorized and
requires a configured provider.
