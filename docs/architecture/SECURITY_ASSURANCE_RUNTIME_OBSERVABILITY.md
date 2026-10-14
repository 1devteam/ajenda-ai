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
