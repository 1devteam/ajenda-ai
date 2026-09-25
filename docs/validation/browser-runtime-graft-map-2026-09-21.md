# GRAFT browser execution map — 2026-09-21

## Scope

Question: how to add bounded web execution (HTTP-first, Playwright-on-demand) without creating a second Ajenda runtime.

This report combines the repository GRAFT+ output with source inspection. It is a planning artifact; it grants no execution authority.

## Machine evidence

Command:

```text
python scripts/validation/graft_plus_gate.py --base-ref origin/main --head-ref HEAD --output /tmp/graft-browser-plan.json --skip-graph-tests
```

Result: the original planning run passed 6/6 steps. The corrected implementation
was subsequently reconciled by the full 7-step GRAFT+ gate.

The corrected canonical graph contains 1,522 nodes and 4,423 edges. It now
includes deployment/runtime support nodes for the browser dependency, worker
image, Compose configuration, startup guard, Chromium binary, and feature flag.

Scenario impact (the proposed browser change surface, not a current diff):

- 15 candidate files inspected
- 154 graph nodes changed/affected as explicit starts
- 233 upstream consumers
- 181 downstream dependencies
- 222 impacted tests
- 10 relevant invariants
- risk domains: external-egress and action-contract
- deployment support is represented by seven nodes and nine source-backed edges;
  the deployment inventory reports zero blocking browser support findings and
  one explicit unknown: the enabled/disabled flag value is externalized through
  the local env file
- relevant existing invariant statuses include `governed-egress=known_violation` and `tenant-isolation=known_violation`; the browser work must not expand either

## Proven current implementation

1. `backend/services/tools/web_actions.py` registers `web.browser_session` in `ActionRegistry`.
2. `backend/services/abilities/catalog.py` declares the action manifest with provider `ajenda_internet`, `EXTERNAL_READ`, high risk, approval required, and evidence required.
3. `backend/services/tools/schemas.py` accepts only one URL, timeout, wait condition, and `extract_text`.
4. `backend/services/internet/browser_session.py` starts one ephemeral Playwright Chromium context, navigates once, extracts title/body text, and destroys the browser/context.
5. URL vetting calls `NetworkEgressAuthority` before launch and again from a route handler for requests, redirects, frames, and subresources.
6. `AJENDA_BROWSER_SESSION_ENABLED` defaults false and fail-closed behavior is implemented.
7. `tests/unit/internet/test_browser_session.py` proves disabled behavior and pre-launch egress rejection; it does not prove real Chromium, multi-step behavior, container availability, or queued worker execution.
8. `scripts/validation/internet_live_proof.py --browser` returned a real `https://example.com` result in this shell. That proof invokes `ActionRegistry` directly with a fabricated proof context; it is not a queued mission/lease/worker proof.
9. The current shell has Playwright installed outside the project dependency declaration. `pyproject.toml` does not declare Playwright, and the API/worker Dockerfiles do not install browser binaries.
10. `backend/services/mission_composition/job_catalog.py` does not list `web.browser_session` as a candidate action. The resolver therefore cannot select it for a composed job today.

## GRAFT gap discovered and corrected

The earlier canonical graph contained `action:web.page_read`, `action:web.search`, and `action:web.research`, but omitted `action:web.browser_session`, even though the action was registered and exposed in the ability catalog and API allow-list.

The current runtime-contract inventory derives action topology from the mission job catalog. That means an action can be executable and policy-declared yet remain absent from the canonical GRAFT action graph when no BusinessJob lists it. This is a graph-observability gap and must be corrected before claiming the browser path is fully mapped.

The graph now inventories registered manifest actions independently of job
selection and adds a deployment inventory for dependency/container/startup
support. The browser action is represented through its explicit observation job,
and deployment completeness is reported from source markers rather than inferred
from documentation.

The runtime impact join also exposes evidence contradictions instead of hiding
them: a completed task whose output has no durable artifact identity is reported
as an artifact-linkage gap, and an admission summary claiming no dispatch while
queue/task evidence shows execution is reported as a contradiction. These are
facts for evaluator review, not automatic repair decisions.

## Required implementation order

### Slice A — Repair the map first

Extend GRAFT inventory to model:

`ability manifest → stable action → input schema → registry handler → runtime authority → egress sink → dependency/container support → evidence contract → eligible job/resolver`

Include registered actions even when not selected by a BusinessJob. Add semantic nodes for `pyproject.toml`, API/worker image dependency installation, browser binary installation, and startup/health checks. Add a finding when an action is manifest/registry-visible but absent from the job/resolver graph.

Proof: the graph must show `web.browser_session` and all unresolved deployment edges; completeness must not silently pass while those edges are absent.

### Slice B — Make the runtime real and bounded

- Pin and install a supported Playwright version in the runtime dependency set.
- Install/pin compatible Chromium support in the worker image; establish whether API-side ability routes also require it.
- Add a readiness/proof check that distinguishes package import, browser launch, and actual navigation.
- Keep the current fail-closed flag and one ephemeral context per task.
- Preserve `EXTERNAL_READ`; no authentication, uploads, purchases, external writes, or arbitrary credential headers in the first slice.

Proof: deployed worker can launch Chromium and a queued read task records claim/start/complete, lease release, action evidence, blocked-request facts, and artifact output.

### Slice C — Add an explicit bounded command contract

Do not pass vague autonomous instructions to the browser. Add a strict, versioned command contract with:

- start URL and allowed origins
- read-only commands initially: navigate, observe, extract, optionally click/type only when separately authorized
- max steps, pages, bytes, runtime, redirects, and downloads
- required artifact fields and completion conditions
- no credentialed URLs or unapproved origins

Return a navigation/step trace and observations through `PageSnapshot`/`ActionResult`/`EvidenceItem`. A browser result is not a completed business artifact merely because a page loaded.

Proof: malformed commands, over-limit commands, cross-origin redirects, private/credentialed destinations, missing required fields, and browser failures all fail closed with evidence.

### Slice D — Integrate composition without making browser the default

Keep the selection order HTTP/search/page-read first. Add browser as a resolver realization only when the mission supplies a concrete URL or an explicit browser-capable requirement that the compiler can represent. Do not add browser as a generic fallback for `Find companies` with no target URL; it cannot replace a search provider by itself.

Update the job catalog, resolver, action input compiler, graph/materialization metadata, and capability/manifest parity checks together. Preserve one `ExecutionTask → queue → lease → WorkerLoop → TaskDispatcher → ActionRegistry` spine.

Proof: a static page uses page-read; a JavaScript-required page selects browser; an unrepresentable request stays blocked or selects another provider; no task bypasses runtime authority.

### Slice E — Close evidence and runtime proof

Add browser provenance to evidence: requested/final URL, origin decisions, step trace, response/status facts, blocked requests, extraction method, content hash or bounded body reference, runtime version, and artifact keys. Keep tenant, mission, task, worker, and lease IDs attached.

Run the real deployed proof, not `internet_live_proof.py` alone:

`compose → confirm → launch → materialize → queue → Redis → WorkerLoop → lease → browser action → evidence → artifact → deliverable`

Join static GRAFT impact with the mission runtime evidence projection and inspect first divergence. Require negative proofs for disabled runtime, missing browser binary, worker-unavailable, blocked destination, timeout, and retry.

## Explicit non-goals

- no second browser subsystem
- no autonomous agent planner inside the browser
- no direct handler execution as production proof
- no browser replacement for paid/public search providers
- no external writes or authentication in the first browser slice
- no claim that the current direct live proof establishes production deployment readiness

## Unknowns requiring proof before the browser path is called production-complete

- whether API ability-runtime paths ever execute browser handlers in-process or only enqueue tasks;
- the exact DNS-pinning/TOCTOU guarantee for Chromium subresource connections;
- whether the deployed environment enables the browser flag and uses the worker image built here;
- whether the new browser job completes through a real queued mission with durable evidence and deliverable reads.

## Implementation reconciliation

The current working tree completed Slice A, Slice B/C, and the narrow business-contract portion of Slice D:

- GRAFT now includes manifest/registry actions even when no BusinessJob selects them. The browser action is represented by `selection:research.observe_web_page:web.browser_session` and the prior `manifest-action-unselected:web.browser_session` finding is absent for a legitimate catalog reason.
- `web.browser_session` accepts a bounded read-only command list (`navigate`, `observe`, `extract`) with exact HTTPS origin allow-listing and a step trace.
- The worker dependency declares Playwright 1.58.0 and installs Chromium with dependencies; worker startup fails closed when browser mode is enabled but Chromium cannot launch.
- Browser action input compilation accepts explicit target URLs only.
- `research.observe_web_page` provides the explicit business contract: a concrete URL and typed observation requirements produce `web_page_observation`. Generic prospect discovery remains unchanged.
- Unit, deployment-contract, type, contract-drift, runtime-authority, migration, ability-rollout, GRAFT+, and direct browser smoke checks passed. The worker image built successfully and a direct Chromium navigation printed `Example Domain`.

The following remain deliberately open and are not represented as completed:

- API-side browser execution, if any, and its deployment contract.
- whether the deployed environment's Chromium resolver rules remain effective for every approved origin;

## DNS hardening reconciliation — 2026-09-24

The browser runtime now resolves every contract-approved host through
`NetworkEgressAuthority` before Chromium launch and passes the resulting
addresses to Chromium's `--host-resolver-rules`. Per-request route vetting is
still retained for redirects, frames, and subresources. Runtime evidence now
reports `dns_pin=chromium_host_resolver_rules` and the pinned host list.

This closes the previously documented `vet_only` gap for approved browser
origins. It does not authorize new origins, credentials, writes, downloads, or
browser-side API execution.
