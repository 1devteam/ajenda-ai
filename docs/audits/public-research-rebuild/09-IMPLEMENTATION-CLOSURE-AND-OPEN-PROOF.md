# Public research rebuild — implementation closure and open-proof record

**Status:** Implemented and merged to `main` on 2026-11-01.  This is a
closure record for issue [#635](https://github.com/1devteam/ajenda-ai/issues/635)
and PR [#636](https://github.com/1devteam/ajenda-ai/pull/636), not a claim that
all public-web or production-environment behavior has been live-proven.

**Merged source revision:** `b8c9a78a5835a0c116e10e183e6f63d497f48490`  
**Reviewed implementation head:** `4c4b6d6f69b78b5ae42f8385851711e17fd1238e`  
**Superseded archive:** PR #634 remains closed and unmerged; no wholesale
archive branch import was made.

The investigation, defect ledger, corrective ownership, causal traces, and
simulation protocol in `00`–`08` remain historical evidence for why this work
was undertaken.  This document records the resulting implementation, its
actual proof level, and the work that must not be inferred from it.

## What changed

| Area | Implemented correction | Truthful outcome |
|---|---|---|
| Governed public search | `web.search` and `web.research` use the governed provider selection path. Brave, SerpAPI, DuckDuckGo HTML, and Instant Answer use `NetworkEgressAuthority`; package-owned DDGS remains excluded. | A provider attempt records its actual provider, HTTP/error outcome, and result contribution. A later fallback does not erase an earlier failure. |
| Network egress | The shared authority rejects credential-bearing URLs, enforces HTTPS and allowed hosts, vets DNS/IP destinations, pins the connection destination, validates redirects, and bounds response reading. | A public hostname is not rejected merely because its text includes an infrastructure word; local/private destinations remain denied. |
| Search/evidence semantics | Challenge pages, rate limits, timeouts, provider errors, valid empty results, raw hits, rejected candidates, and verified identities are represented separately. Distinct URLs are not deduplicated only because titles match. | HTTP success or a raw search hit does not become a verified business. |
| Identity and contacts | Public identity verification requires source-backed company evidence; HTTP error pages and weak third-party matches cannot verify a company. Contact observation emits only usable contact values. | A verified company with no email or phone remains a company observation, not a fabricated contact observation. |
| Mission graph and qualification | Public identity-only research binds verified candidates into qualification; contact observation is not implicitly required. Composition targeting facts no longer manufacture a prospect or fill absent company attributes. CRM-only behavior remains covered separately. | A genuinely valid empty upstream result scores zero companies; missing, malformed, or failed upstream inputs remain fail-closed. |
| Valid-empty lifecycle and operator artifact | The binder, runtime contracts, artifacts, and deliverable projection preserve whether no candidates were found, candidates were rejected, a provider failed, or input was invalid. | Operational task completion remains distinct from satisfying a requested commercial quantity. |
| Browser containment | The ephemeral Chromium path constrains requests to GET/HEAD, blocks WebSockets, service workers, downloads, credentials, off-origin/port navigation, and non-success responses, with per-request egress vetting. It remains feature-flagged off by default. | Browser installation or source code presence is not evidence that a deployed worker has run this lane. |
| Schema/release coherence | The dedicated migrator upgrades then verifies the image's single Alembic head. API, worker, and assurance verify the same invariant and surface schema readiness instead of self-migrating. | No persistent database was reset, stamped, or rebuilt to hide drift. A particular production database is still unverified until an operator runs the release procedure against it. |

## Finding disposition

The original O01–O10 and later R01–R20 classifications are intentionally not
retrospectively relabeled as a single finding system.  Their source basis is
preserved in the preceding audit documents.  The implementation disposition is:

| Ledger group | Disposition | Primary owners and proof |
|---|---|---|
| O01–O04; R08, R12–R15 | Repaired | `internet/search.py`, `standalone_actions.py`, provider and action tests; provider-attempt lineage and governed fallback are retained. |
| O05; R04, R05, R07 | Repaired in deterministic and runtime-contract proof | research input, identity policy, contacts/identity observers, page-read status handling, and causal simulation. External real-company verification remains separately gated. |
| O06; R11, R18 | Implemented with deterministic/controlled tests; deployment proof remains open | `browser_session.py` enforces the read-only transport contract. A feature-gated real Chromium proof is still required for any browser rollout. |
| R01, R02, R06, R16, R17 | Repaired | composition, binding, qualification, typed artifacts, deliverable projections, and causal/runtime tests distinguish true empty from bad input and do not synthesize prospects. |
| R03, R09, R10, R20 | Repaired | `page_read.py` and `network_egress.py` tests cover unsuccessful pages, bounded reads, credentialed URLs, and safe hostname behavior. |
| R19 | Partially resolved by evidence boundaries and gated test harness | The system has deterministic end-to-end and pre-merge fixture proof, but no completed external positive Dallas/HVAC mission is claimed below. |

## Evidence executed before merge

### Local evidence

The final local full suite ran on the implementation head and reported:

```text
3802 passed, 9 skipped, 1 warning in 1241.31s
coverage: 83% combined line and branch coverage
```

The skipped cases were explicitly gated external-provider/credential proofs;
they were not treated as passing live evidence.  Focused database role and
migration checks also passed after the integration fixture corrections:

```text
4 passed
```

The standard non-integration gate also exposed four contract mismatches created
by the release/readiness and egress changes.  They were corrected before the
final full-suite result: stale graph control data, webhook pinning test doubles,
readiness response expectations, and schema-aware test-app startup.

### Pull-request evidence

At implementation head `4c4b6d6f`, PR #636 passed its completed CI checks:

- unit and integration tests;
- migration round-trip;
- lint/type, dependency, secret, and GitGuardian scans;
- Docker builds for API, worker, migrator, and frontend;
- Trivy scan;
- canonical-graph, blast-radius, runtime-contract, and graph-selected checks;
- pre-merge live runtime proof; and
- recovery-hardening and worker-build checks.

The separately named **Live Runtime Proof** workflow was **skipped by workflow
configuration**.  It is not represented here as an executed proof.  The
pre-merge runtime proof is a deterministic fixture lane and does not prove an
external search provider or a real public business identity.

## Still unproven — required before stronger claims

1. **A positive external public-research mission.** Run the opt-in
   `AJENDA_LIVE_PUBLIC_RESEARCH=1` proof with a configured governed provider.
   It must show a real returned URL, page observation, verified-or-rejected
   identity evidence, qualification disposition, evidence persistence, and
   fresh-session deliverable readback. A valid empty result is acceptable as a
   research result, but it is not evidence that positive discovery works.
2. **A controlled real Chromium containment run.** With
   `AJENDA_LIVE_BROWSER_OBSERVATION=1`, use a controlled receiving server to
   show that attempted POST/PUT/PATCH/DELETE, WebSocket, service-worker,
   download, and different-port paths are blocked before an external effect.
   Do not enable the browser feature globally merely to run this proof.
3. **Release-environment schema proof.** For each real deployment, build and
   run the migrator from the exact release image, then verify the live
   database's Alembic revision equals that image's single head before API,
   worker, or assurance starts. The merged code proves the guard; it does not
   attest to any environment not inspected by that release procedure.
4. **Post-merge full Compose proof when promotion requires it.** Dispatch the
   workflow with `run_live_proof=true` or run the documented prod-like command.
   Preserve its artifacts and record whether it is fixture-only or
   provider-backed. The skipped PR workflow cannot be substituted for this.
5. **Independent review of real artifacts.** Review persisted provider attempts,
   source URLs, gaps, verified identities, rejected candidates, and deliverable
   acceptance after the external and browser proofs. Do not accept handler
   returns or test mocks as durable-evidence proof.

## Operational notes that remain binding

- Use the dedicated migrator as the only schema writer. Do not stamp, reset,
  truncate, rebuild, or self-migrate a persistent database to resolve drift.
- Keep DDGS disabled in the governed chain unless its package-owned transport
  can be made subject to the same egress contract and receives its own evidence.
- Keep `AJENDA_BROWSER_SESSION_ENABLED=false` until the controlled browser
  proof is recorded for the target image/environment.
- Preserve provider-attempt history even where fallback returns useful results.
  Operator conclusions must distinguish provider failure from no result.
- A task can complete operationally with an insufficient-evidence deliverable;
  this never authorizes outreach or satisfies a commercial quantity on its own.

## Recommended next work

The next corrective work is **evidence collection, not another broad rebuild**:
run the two gated live proofs and the release schema procedure above, review the
fresh artifacts independently, then either close the remaining proof gap or
open a narrowly scoped issue with the actual failing owner and evidence.
