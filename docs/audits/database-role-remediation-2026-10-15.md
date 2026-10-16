# Database role remediation evidence — 2026-10-15

## Scope and authority

This change separates the Ajenda migrator, API, worker, and continuous-assurance
PostgreSQL identities.  It does not change mission authority, queue dispatch,
or tenant policy semantics.  PostgreSQL remains the enforcement authority for
grants and RLS; application configuration only fails closed before startup.

## Implemented controls

- `deploy/sql/database_role_bootstrap.sql` hardens both new and existing
  identities: no runtime role is superuser, `BYPASSRLS`, a database/role
  creator, inheriting, or a member of another role.
- Migration `0052_db_role_separation` requires the bootstrap transition,
  moves table ownership to `ajenda_migrator`, removes legacy `admin_bypass`
  policies, and grants runtime privileges without ownership.
- Migration `0053_restrict_auth_runtime` removes worker and assurance access
  to deliberately pre-tenant authentication records.  The API retains this
  access for sign-in, signup verification, and session refresh.
- Every production-like process validates both its primary and optional vector
  database URL against its declared least-privilege identity.
- Compose bootstraps roles before migrations. Kubernetes manifests supply an
  identity-specific URL to each API, worker, and migrator workload; an
  independently authorized operator must complete role bootstrap before the
  migration Job.

## Runtime proof

The isolated PostgreSQL integration test intentionally elevated
`ajenda_worker`, gave it an elevated-role membership, ran the actual bootstrap
SQL, and proved that all prohibited attributes and memberships were removed.
The same integration suite proved API and worker tenant-context isolation,
denial of cross-tenant billing writes, denial of worker/assurance access to
pre-tenant authentication tables, and denial of DDL/RLS/role escalation.

The running local stack reported revision `0053_restrict_auth_runtime`; API,
worker, assurance, and migrator roles all reported `rolsuper=false` and
`rolbypassrls=false`, with zero direct memberships. The API health endpoint
returned `{"status":"ok"}`.

## Validation record

Passed:

- focused role/configuration/deployment tests;
- real PostgreSQL role, auth, onboarding, billing, and queue integration
  tests;
- canonical migration upgrade/downgrade/upgrade rehearsal;
- Compose production-like configuration resolution;
- migration seed, runtime authority, ability-rollout, contract-drift, and
  G.R.A.F.T.+ reconciliation checks.

The graph impact report selected tenant-isolation, runtime-authority,
persistence, configuration, runtime-secret, retry, and side-effect proof
bundles. It also identified `deploy/sql/database_role_bootstrap.sql` as an
unmapped deployment artifact; this is a G.R.A.F.T.+ coverage gap, not evidence
that the bootstrap is absent.

## Remaining release blockers

- The broad Ruff gate has five pre-existing import-order failures outside this
  change.
- Mypy reaches an existing error in
  `backend/services/mission_runtime_evidence_projection.py:595`.
- The full non-integration suite additionally exposes an unrelated frontend /
  backend operating-charter default mismatch.
- Production provisioning remains unverified. In particular, an operator must
  execute the bootstrap procedure with a separate administrator identity and
  verify the resulting role catalog before any Kubernetes or future cloud
  deployment receives traffic.

**Production-security verdict: NO-GO pending the unrelated repository gates
and a real deployment-specific provisioning/restore exercise.**
