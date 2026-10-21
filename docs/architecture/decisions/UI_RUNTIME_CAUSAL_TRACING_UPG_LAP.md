# UI-to-runtime causal tracing — UPG/LAP

## Responsibility

This capability records consequential UI interaction observations and their
authenticated server-side consequences. It accepts bounded, redacted browser
events; associates them with a server-issued interaction identity; appends
immutable facts to Ajenda's existing `audit_events` runtime-evidence ledger;
and projects a read-only lifecycle artifact. It does not authorize requests,
issue credentials, alter mission execution, or control providers.

The first producer path is LinkedIn OAuth. The reusable contract permits later
instrumentation of other consequential controls, but does not claim coverage
for them until they emit and are tested.

## Source of truth and dependencies

- Durable-fact owner: `backend/domain/audit_event.py` and
  `backend/services/runtime_evidence_ledger.py`.
- Tenant transaction owner: `backend/app/dependencies/db.py` and
  `backend/db/session.py`.
- OAuth authority: `backend/api/routes/provider_credentials.py`,
  `backend/services/credentials/linkedin_oauth_connect.py`, and the existing
  credential-management service.
- Browser producer: `frontend/src/pages/CredentialsPage.tsx` and
  `frontend/src/api/client.ts`.
- Read-only projection owner: a new interaction projection alongside the
  existing mission runtime-evidence projection.
- Graph/proof contracts: the canonical dependency graph plus the G.R.A.F.T.+
  changed-file impact and proof-selection workflow. Generated local proof
  artifacts are intentionally not repository contracts; they are recreated
  for each validation run.

## Dependencies and handoffs

`browser local interaction id` -> `telemetry ingestion` -> `server-issued
interaction id` -> `OAuth authorize route` -> `credential callback route` ->
`audit ledger` -> `read-only interaction projection` -> `G.R.A.F.
reconciliation/export`.

Browser observations are untrusted. The API derives actor and tenant from the
authenticated request and validates any local/server correlation association.

## Possible pitfalls

- Browser telemetry can be lost, blocked, retried, duplicated, delayed, or
  reordered.
- A browser event can claim an invalid actor, tenant, action, or predecessor.
- OAuth URLs, codes, state, bearer tokens, and client secrets are sensitive.
  The opaque interaction identifier travels only inside signed OAuth state to
  associate a callback; it is not included in runtime evidence payloads.
- Returning before a transaction commits could falsely claim durable evidence.
- A duplicate interaction must not create a second credential or mutate a
  prior record.
- A tenant must not retrieve another tenant's interaction projection.
- A missing callback can be an unfinished flow, telemetry loss, or provider
  failure; it is not itself proof of failure.

## Invariants

1. `audit_events` remains the only canonical durable fact store for this
   evidence; projection and G.R.A.F.T. remain read-only consumers.
2. Browser events never grant authority. Authentication, authorization, tenant
   identity, provider choice, and credential persistence remain owned by the
   existing API path.
3. Client event IDs are idempotent per tenant and producer. Arrival order never
   becomes causal order; predecessor references and producer sequence are
   preserved separately from receipt time.
4. An acknowledgement labelled `persisted` is returned only after its database
   transaction commits. Export identity is reported only by an actual
   projection/export operation.
5. Raw OAuth URLs, authorization codes, state, tokens, client secrets, and
   request headers are not placed in browser telemetry, ledger facts, logs, or
   projections.
6. Missing, delayed, unavailable, not-applicable, and historical evidence stay
   distinguishable from observed denial or failure.
7. Observer or projection failure cannot block OAuth, credential persistence,
   mission execution, or other canonical runtime behavior.

## Proof plan

- Unit proof for envelope redaction, identity association, deduplication,
  out-of-order events, lifecycle classification, timeout/indeterminate state,
  and earliest supported divergence.
- HTTP/API proof for authenticated ingestion, denied access, cross-tenant
  projection isolation, durable acknowledgement, and LinkedIn authorization
  facts.
- Browser proof for click/handler/request/redirect producers and telemetry
  failure not blocking OAuth initiation.
- Integration proof compares independently captured browser event input and
  API route observations with the exported projection, including deliberate
  duplicate, delayed, out-of-order, denied, and callback-exchange failures.
- Required gates include Ruff, formatting, mypy, frontend build/tests,
  migration validation, graph reconciliation, selected integration tests, and
  a committed-runtime artifact review.

## Implemented boundary and verification record

The first vertical producer is deliberately limited to LinkedIn connection
initiation and callback completion.  It records browser click, handler,
request, and redirect observations; authenticated API receipt and permission
observations; authorization URL issuance; callback receipt; and either
credential persistence or a provider-exchange failure.  The exported
projection is `graft_ui_runtime_interaction_evidence` schema `1.0.0`; its
digest covers the projection and enumerates the immutable audit-event IDs it
contains.

Verification uses a real PostgreSQL HTTP integration fixture, not a
projection-only fixture.  It independently supplies the browser-style events,
executes the API authorization and callback paths, and retrieves the resulting
projection.  It proves the completed path, a deliberately induced exchange
failure, duplicate delivery, out-of-order causal references, timeout-driven
indeterminate coverage, cross-tenant denial, and redaction of OAuth material.

No live LinkedIn provider exchange is included in this repository proof: that
requires a separately authorized tenant connection and real provider
configuration.  The production OAuth result must be validated after that
configuration is available; the runtime artifact will then show either its
credential-persisted terminal fact or a documented terminal failure.
