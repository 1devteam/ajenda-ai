# Runtime information observability and security monitoring

## Separation of responsibility

**Ajenda Runtime** remains the sole owner of mission admission, queue/lease control,
provider execution and canonical state mutation.

**Runtime evidence projection / G.R.A.F.T.** observes tenant-scoped state and
recorded information flow. It does not recommend architecture changes or grant
authority. Its output contains facts, observations, and explicitly qualified
diagnostics.

**Continuous Assurance** is being migrated to the security-monitoring
responsibility. Its primary security result is
`AssuranceSnapshot.runtime_summary.security_status`:
`alert` when a positive security finding exists, and
`no_findings_observed` otherwise. This is a *bounded observation*, not
a declaration that a tenant is secure. The loop prioritizes queued, running, and paused missions, then newer
historical missions, within the configured per-tenant mission limit.
This limit means monitoring coverage may be incomplete for tenants with
more concurrent active missions than the cap.

The legacy `AssuranceSnapshot.status`, semantic-drift findings and aggregate
operational metrics remain readable for compatibility during this migration.
They must not be presented as the security verdict. The daemon emits a
separate `ajenda_runtime_security_alerts` error log when security findings
are observed. It does not suspend missions, alter permission decisions,
rotate credentials or perform other external effects.

## Positive security findings

Security monitoring checks records observed under the tenant's scoped
mission against canonical mission and task ownership, lease/task linkage,
evidence provenance, and the mandatory no-execution-authority invariant of
mission information audit events. A versioned running or terminal task without
a matching recorded lease is reportable. Historical absence without a
recorded applicable contract is **unknown**, not evidence of attack.

All security findings contain category, code, severity, and identifiable
source record. A finding is not itself proof of a successful exploit.
Independent database-role/RLS and live admission tests remain necessary.

## Live information-flow evidence

Tenant-scoped information observations use the existing audit ledger,
not another event store. Version 1 records bounded representations at:

- mission confirmation: intake, task graph and planned-step shape, selected
  technical outcome and action identifiers, proposal reference;
- execution start: task/lease references, input-binding and declared-output
  representation;
- execution completion: task/lease references, output representation and
  generated evidence record identifiers;
- execution failure: task/lease references and a non-sensitive failure code.

The existing authenticated `/{mission_id}/runtime-evidence` read route
exposes these as ordered `information_flow` entries. The existing
`task_flows`, `record_flows`, and read models retain the more detailed
governed information context. New audit records never copy raw prompts,
provider responses, credentials, or full record values.

A representation digest fingerprints *shape*, not private content. It is
not source authentication, semantic equivalence, or a replacement for
canonical artifact evidence.

## Remaining verification

The change set requires full unit and integration verification, tenant/RLS
adversarial tests, and an end-to-end actual mission in a deployed environment.
Do not claim provider outcome, crash recovery, complete RLS, or security
coverage from static graph or unit fixtures.

The permission-scoped `/missions/{mission_id}/runtime-reconciliation-export`
route now seals a snapshot generated from canonical runtime projections. It
retains record identities and distinguishes collected/verified evidence from
rejected evidence. The exported digest verifies self-consistency, but a copied
file still requires independently authenticated provenance to prove its origin.
The validator therefore keeps `source_authenticity_verified=false`.


## Information observability sufficiency contract

The authenticated runtime-evidence read model now exposes both
`information_flow` (actual ordered producing observations) and
`information_coverage` (expected observations with explicit applicability).
These sections are **not synonymous**: a missing historical event is not
proof of a broken contemporary contract.

Each emitted representation includes bounded nested field paths, type labels,
cardinality and a **structure-only** fingerprint, never raw data values.
Worker-start evidence includes input bindings, current resolved input shape,
declared output contract and tool invocation shape. Worker-completion events
link generated evidence records to the output shape. The projection separately
retains task output summaries, artifact keys, source lineage, evidence status,
and chronological audit records.

Coverage reports `recorded`, `missing_under_active_contract`, or
`not_recorded_or_legacy` for task start and applicable terminal stages.
A missing `composition_confirmed` event is treated as
`not_recorded_or_legacy` until a producing contract is known.

**The following are not established by structural telemetry alone:**

- Fidelity of the original prompt-to-intent semantics or correctness of
  transformations that preserve the same field structure
- Actual provider requests/responses and external effects absent canonical
  provider receipts
- Completeness of observation for pre-confirmation proposals or abandoned
  composition attempts
- End-to-end correlation for failures outside committed transactions
- Runtime evidence that these fields are populated in a deployed credentialed
  mission rather than represented only in tests

For full investigation, follow tenant-authorized references back to canonical
mission intake, proposal, task, lineage, provider and evidence records. Never
replace those records with monitoring copies. Before declaring sufficiency,
execute one real mission and check every applicable stage against its durable
source record, including rejected actions and recovery paths.
