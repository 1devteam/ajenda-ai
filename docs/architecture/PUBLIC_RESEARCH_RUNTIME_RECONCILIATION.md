# Public Research Runtime Reconciliation

## Scope and decision

This change restores evidence-limited public business research through the
existing composition, runtime, network-egress, verification, qualification,
and artifact owners. It does not add automatic outreach, provider writes, a
new search authority, or a second browser system.

The governing runtime path is unchanged:

`compose -> confirm -> launch -> task graph -> queue -> lease -> dispatcher -> action -> evidence -> artifact`

`web.research` and `web.search` now use the configured public-search chain.
The free general-search fallback is DuckDuckGo's HTML endpoint through
`NetworkEgressAuthority`; the retained DDGS adapter is deliberately not put
back on the runtime chain because it owns its own transport.

## UPG/LAP record

| Item | Result |
|---|---|
| Responsibility | Produce bounded public search observations, verify candidates independently, and qualify only evidence-supported commercial relevance. |
| Sources of truth | `internet/search.py`, `network_egress.py`, browser session, composition/catalog/binding owners, task contracts, and persisted runtime evidence. |
| Dependencies | Existing governed task lifecycle, egress authority, provider configuration, verifier, qualification action, materializer, PostgreSQL/Redis runtime proof. |
| Pitfalls | Package-owned transport, private/redirected destinations, browser writes, false hostname blocks, raw hits treated as identities, targeting constraints treated as facts, and empty research treated as task failure. |
| Invariants | All actual HTTP search providers use egress authority; DDGS is not selected; browser requests are GET/HEAD only; a hit is not an identity; market constraints are not prospect facts; valid emptiness is durable evidence, while missing/malformed input still fails. |
| Proof | Unit tests, two isolated PostgreSQL/Redis live runtime proofs, actual worker Chromium observation, static gates, and the repository regression suite. |

## Finding disposition

| Finding | Disposition | Existing owner / action |
|---|---|---|
| F01–F02 | Confirmed and repaired | `public_search()` now drives both research and search actions. |
| F03–F05 | Confirmed; preserve providers, correct the boundary | Governed Brave, SerpAPI, DuckDuckGo HTML, and Instant Answer are distinct. HTTP success with no hits is an empty observation, not a no-company conclusion. |
| F04 | Confirmed as an over-broad compatibility/security change | DDGS remains installed but unselected because its package-owned transport bypasses shared egress controls. |
| F06 | Confirmed and repaired | Query variants use the stated scope plus official/business-site variants; no universal `local contractor` suffix. |
| F07 | Confirmed; preserved as a restriction | DDGS is not reconnected until it can demonstrate equivalent transport controls. |
| F08 | Confirmed and repaired | Hostname blocking is exact/reserved and DNS/IP based, not substring based. |
| F09 | Partly confirmed | Capability choice remains composition's role; task authorization remains runtime's role; egress constrains each request. No new authority was added. |
| F10, F12 | Confirmed | Chromium installation and readiness are separate; the enabled worker performed a real read-only observation. No global rollout policy was changed. |
| F11, F14 | Partly confirmed | Browser observation remains explicit and URL-bound; it is not automatically invoked for every hit. |
| F13 | Confirmed source risk and repaired | Browser routing rejects non-GET/HEAD requests, blocks WebSockets/service workers/downloads, and preserves origin, credential, and egress checks. |
| F15–F16 | Confirmed and repaired | Evidence now identifies the actual provider and retains each provider attempt, result count, status, and error. |
| F17 | Confirmed; preserved | Search hits remain unverified candidates until the existing identity verifier provides evidence. |
| F18 | Partly confirmed and repaired | Mission targeting constraints remain qualification context; they no longer populate an individual prospect's observed industry, location, intent, or opportunity. |
| F19 | Confirmed and repaired | Declared terminal research stages can complete with a non-empty research gap and empty output; malformed or missing bindings still fail closed. |
| F20 | Confirmed and expanded | Provider-chain, browser, empty-result, binding, runtime, and fresh-session integration coverage was added. |

Additional findings: quantity phrases no longer become an industry value (for
example, `up to three HVAC`); query variants receive bounded shares of the
candidate budget; and public qualification uses the verifier's artifact rather
than a competing implicit contact-observation artifact.

## Runtime proof and limits

`tests/integration/runtime/test_public_research_runtime_live.py` performs two
opt-in, isolated PostgreSQL/Redis proofs through real routes, queueing, leases,
`TaskDispatcher`, evidence persistence, materialization, and fresh-session
readback:

1. a public Dallas HVAC research/verify/qualify mission; and
2. an explicit browser observation of `https://example.com`.

The research proof accepts a real evidence-backed empty result. It does not
invent a company, need, buying intent, or outreach recipient to meet a count.
The browser proof is read-only. Neither proof sends, modifies, labels, archives,
or contacts an external party.

No assertion here establishes that a verified business has purchasing intent.
That remains an explicit uncertainty or qualification gap until independent
source evidence supports it. Brave and SerpAPI routes are implemented but were
not live-tested without configured credentials; the governed DuckDuckGo HTML
route is the exercised no-credential discovery route.
