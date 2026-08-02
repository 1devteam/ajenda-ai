# ADR-0009: External connector truthfulness and simulation boundary

- **Status:** Accepted
- **Date:** 2026-07-31
- **Authority class:** Runtime tool policy and declarative mission composition

## Context

Several external-read handlers retained simulated success responses for local tests. Mission composition could select those actions without a concrete connection, which allowed a proposal or runtime result to look externally sourced when no provider credential existed. Connector-specific natural language could also be widened into a different query or public-web fallback.

## UPG / LAP review

**Responsibility:** composition must preserve the requested provider and query scope; runtime handlers must either use a tenant-scoped credential or fail closed. Simulation is test/local proof behavior and never the default runtime result.

**Dependencies:** mission intent interpretation, job catalog, capability resolution, action-input compilation, provider credential resolution, GitHub/Google Calendar/Gmail/LinkedIn/Salesforce handlers, action evidence, and connector unit tests.

**Possible pitfalls:** missing credentials, an explicit provider silently replaced by public search, unsupported Gmail or CRM filters being dropped, simulated evidence presented as real, cross-test environment leakage, credentialed network failure being replaced by simulation, and inconsistent policy across handlers.

**Invariants:**

1. Missing external credentials fail closed unless `AJENDA_ALLOW_SIMULATED_EXTERNAL` is explicitly enabled in a non-production environment; `AJENDA_ENV=production` always rejects simulation.
2. Credentialed provider failure never falls back to simulation.
3. Explicit HubSpot sourcing cannot be replaced by public-web discovery.
4. A connection hint requires that connection before the action is ready.
5. Unsupported material query scope is rejected rather than silently widened.
6. Simulation tests opt in per test and cannot alter the default production posture.

**Proof:** targeted provider tests cover simulated opt-in and credentialed failures; policy tests cover default denial and production override rejection; mission-composition tests cover connector vocabulary, readiness, HubSpot source preservation, Gmail keyword-clause preservation, and unsupported scopes. Repository validation gates remain authoritative before merge.

## Decision

Centralize the uncredentialed external-read decision in `external_sim_policy.py`. Default to denial and ignore the simulation opt-in whenever `AJENDA_ENV=production`. Keep simulation implementations only for explicitly opted-in local/unit proof. Require connector readiness in capability resolution and reject natural-language scopes that the selected provider input cannot faithfully represent.

## Compatibility and rollback

This is intentionally stricter: callers that depended on implicit simulated external success must supply a credential or explicitly enable simulation in a non-production environment. Rollback is a revert of this change; it would restore misleading success behavior and is not recommended.

## Frontend dependency review

The frontend now keeps `react-router-dom` and its `react-router` override on the same 7.18.2 release instead of mixing major versions. As of this review, `npm audit --omit=dev` reports GHSA-qwww-vcr4-c8h2 against React Router's RSC/server-action mode. Ajenda is a client-only Vite SPA and does not enable RSC or React Router server actions, so the vulnerable execution path is not present. Downgrading to 7.11.0 would reintroduce multiple older XSS, open-redirect, deserialization, and denial-of-service advisories. The upstream maintainer advisory currently lists 7.18.2 as patched, while GitHub's reviewed advisory database still lists only 8.3.0 and continues to drive the `npm audit` finding. This source discrepancy remains recorded; keep the aligned 7.18.2 install, monitor the reviewed database, and upgrade when the 7.x metadata is reconciled or a compatible later release is available.
