# Rebuild execution order — independent engineering proposal

## Scope

Rebuild the public-commercial research remediation from the current `main` implementation. Do not copy PR #634 in bulk. **Primary architectural authority is the historical source-backed investigation reconstructed in `00-ORIGINAL-INDEPENDENT-INVESTIGATION.md`** (not the later F01–F20 shorthand). PR #634's exact source and tests are archived and indexed in `01-PR634-SALVAGE-INDEX.md`; post-PR defects and invariants are in `02-INDEPENDENT-DEFECT-LEDGER.md`. Preserve the completed internal CRM checkpoint, core composition/runtime authorities, provider security controls, evidence persistence and artifact read models.

This is the reviewer's **separate proposed resolution design**, not a directive that the implementation engineer must accept without independently checking the code. Restore the original separation: **mission authority permits work; capability strategy chooses approved providers; network security admits connections; existing runtime executes; evidence records what occurred.** Browser rollout is distinct from authorization. Do not introduce a new governance layer or use a browser risk to disallow governed general search.

## Stage 0 — establish exact baseline and behavioral ownership

1. Identify current `main` SHA and existing tests for the complete paths `instruction → MissionIntent → action input → graph → admission → queue/lease → handler → provider → evidence → binder → verifier → qualify → materializer → operator readback`.
2. Compare source against archived head `5fbc84ab`. Adjudicate **O01–O10** from the uploaded original investigation separately from **R01–R20** post-PR findings. If referencing the later F01–F20 handoff, check the actual source before claiming exact identifier equivalence. Record `base present`, `PR introduced`, `PR exposed`, `PR repaired incompletely`, or `disproved` with exact proof.
3. Write **failing tests before repair** for at least the highest-risk invariants R01–R04, R09–R11, R13 and R16. Do not count an existing green test that encodes the wrong expected semantics.
4. For proposed code outside this review's list, trace all consumer data contracts before touching it; avoid a new framework.

## Stage 1 — trusted outbound observation transport

Owners: `network_egress.py`, `url_safety.py`, `page_read.py`, `browser_session.py`; indexed candidates from archived PR for hostname and browser guards.

- Reject credential-bearing userinfo at the network boundary before pinned URL construction; explicitly preserve existing credentialed integrations with distinct authorized header transport.
- Make network response truncation a **streaming byte limit** before decoding, not post-download slicing.
- Normalize public DNS/IP policy, blocked reserved suffixes and valid publicly resolved hostnames. Treat `.local` suffix differently from harmless internal labels.
- Page-read status must not indicate a successful observation for HTTP errors or network/provider challenge pages.
- Browser read-only transport should deny non-GET/HEAD, WebSockets, service workers, downloads and invalid scheme/origin/port; preserve DNS pinning and allowed hostname policy. Use real Chromium + controlled local test server or authorized equivalent test harness (no public write traffic).

Gate: deny unsafe network destinations and browser actions, prove relevant response bounds and permitted destinations, and retain per-action authorization. **Do not use unrelated transport-hardening gaps as a blanket ban on governed general search.** A search provider can be selected when its actual transport satisfies the existing relevant security contract; wider shared-egress hardening can proceed in the same coordinated branch with clearly assigned test gates. Chromium rollout remains independently disabled until its interactive safety evidence passes.

## Stage 2 — effective general search with true provider provenance

Owners: `internet/contracts.py`, `internet/search.py`, `tools/standalone_actions.py`.

- Use existing `public_search` through both actions.
- Salvage attempt dataclasses, governed HTML parser, free provider priority and scoped query variants only after confirming actual endpoint responses, output limits and governance.
- DDGS remains unselected unless its transport can meet shared egress; explicit settings must not silently misroute.
- Differentiate provider error/429, challenge/unrecognized HTML, meaningful empty general search, Instant Answer empty response, hit returned, and identity verified.
- Deduplicate identical URL observations; never remove distinct candidate URLs solely because results share title text.
- Persist source/provider attempts and scope partitions through **web.research and web.search**. Search text is untrusted observation, not a prospect.

Gate: valid positive search, valid empty, denied/challenged/malformed provider, fallback, duplicates, URL safety and truthful attempts pass deterministic tests. Then a controlled real outbound read proves actual general result handling.

## Stage 3 — candidate verification must be evidence-backed

Owners: `web_action_contacts.py`, `web_action_identity.py`, `web_action_identity_policy.py`, `action_input_research.py`.

- Remove market category from named-company field for open-ended research; maintain actual named-company semantics for explicit requests.
- Require independent company identity evidence; result URL equality cannot prove ownership. Preserve official site/link source, exact name evidence, industry/location evidence and contradicting third-party context.
- Handle short industry labels and short city/state codes; no unrequested Dallas default. An unspecified field stays unspecified.
- A real HTTP 403/404/503 page, search listing, affiliate/lead-generation page or page carrying only generic local-market text never becomes a verified company.
- An actual verified company with no phone/email remains verified as a company; it does **not** satisfy a contact-collection objective.

Gate: realistic positive company, malicious/false-positive page, irrelevant industry, wrong locality, no-contact, directory and short abbreviation examples all pass; no loss of internal CRM evidence semantics.

## Stage 4 — binding, qualification and materialization truth

Owners: `mission_composition/action_input_sales.py`, `capability_resolver.py`, `job_catalog.py`, `plan_compiler.py`, `mission_runtime_projection.py`, `mission_input_binding.py`, `worker_runtime_contracts.py`, `sales_action_qualification.py`, `deliverable_runtime_artifacts.py`, `deliverable_runtime_read_model.py`.

- Eliminate generic market-based pseudo-leads as materializable prospects. No fallback to composition seed when upstream explicitly completed empty.
- Do not merge unverified or target-only company attributes into an observed prospect, including the first one; qualification scores depend only on evidence-backed facts and configured rules.
- Separate completed-empty, all candidates rejected, provider failed, malformed binding, missing upstream and never-executed producer; only the first two may legitimately produce evidence-backed empty terminal artifacts.
- Contact collection must be explicit when requested, never implicit for a pure identity-only mission; positive empty company/no contact remains truthful.
- Preserve the exact cause of no evidence for operator-facing readback. Task execution complete != commercial deliverable complete.
- Preserve legacy internal CRM graph and explicit contact path.

Gate: every malformed/missing input rejects, every valid empty returns zero scored and zero qualified fake rows and an explanatory readback, positive identity yields an evidence-backed scoring disposition, and CRM regression remains identical.

## Stage 5 — end-to-end proof before acceptance

1. Deterministic local/CI tests: provider × host × HTTP status × candidate evidence × contact observed × binding completeness × approval status.
2. Real PostgreSQL/Redis runtime: compose → confirm → launch → queue → lease → dispatcher → governed external GET → evidence persistence → materialized artifact → fresh-session operator readback; verify per-task authority and tenant isolation.
3. **Positive** public research must show at least one genuinely returned search URL and correctly attributed verified/rejected business evidence; do not force fabricated purchase intent or numeric count.
4. **Negative** public research: provider valid-empty; challenge/rate-limit; all rejected; no contact; malformed input; blocked navigation/POST/WebSocket.
5. Chromium under controlled server: verify prohibited outbound method never reaches receiving endpoint; no automatic browser rollout.
6. Run Ruff, formatting, mypy, canonical GRAFT runtime adjudication, contract drift, tenancy, CRM regression, integration/migrations and full CI.
7. Record each **O/R** finding disposition and link the exact test and fresh persisted evidence. Any later F-number must first be checked against the actual subsequent handoff. Do not claim success solely because a general pre-merge operator proof passed.

## Change management

- Recovery branch is created from `main` and initially contains **only** the preservation/index/independent findings. Code is not yet implemented.
- Work in coherent commits by the responsible existing owner; use **one substantial final implementation PR** after tests prove each stage. Avoid 10+ incremental PRs.
- Engineering reviewer evaluates implementation independently against this ledger and **does not change acceptance criteria after the fact** without recording genuinely new source evidence.
- Codex/implementation engineer independently validates or disproves findings and may propose a better repair with evidence; it must not interpret this proposal as already proven code.
- The archive PR branch is read-only reference; do not delete while needed. Close draft #634 **without merge** once this index and new branch exist.

## Milestones

- **M0 — preservation secured:** exact #634 commit archived; index, defect ledger and proposed rebuild order committed on clean baseline.
- M1 — proportionate network safety and relevant observation transport proven, without conflating provider strategy with governance.
- M2 — provider/search provenance and real discovery proven.
- M3 — identity and contacts evidence boundary proven.
- M4 — empty/positive qualifications, artifact readback and CRM regression proven.
- M5 — independently reviewed runtime proof and CI complete; only then candidate for merge/release.
