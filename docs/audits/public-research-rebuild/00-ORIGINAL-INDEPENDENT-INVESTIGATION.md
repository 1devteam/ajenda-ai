# Original independent investigation — canonical architectural findings

**Provenance:** The user supplied the full 423-line historical discussion as `Pasted text(20261027-191943).txt` on 2026-10-27 and explicitly identified these as the reviewer's **original findings**. This document is a *faithful, structured engineering reconstruction* of that source. It is **not** a claim to be a verbatim copy, and it is **not** the later F01–F20 adjudication handoff. The source document did not number its findings F01–F20. Preserve that distinction.

**Source context:** Ajenda-AI **before** draft PR #634. Assess current main and archived PR #634 separately before claiming an original defect persists or was fixed.

## The original architectural claim

The root problem is **confused responsibility**, not insufficient or excessive security. The existing components should retain their boundaries:

```text
Mission intent + authorization       → what work may be performed?
Research capability/provider choice → which approved search/page/browser mechanism best fits?
Network and browser security        → which destinations and request operations are allowed?
Existing worker execution           → queue, lease, tenant, action authority, dispatch
Evidence + commercial evaluation    → what was observed, what remains unknown, was intent satisfied?
```

**Do not introduce another architectural layer. Do not weaken private-network protections.** Network egress policy cannot silently force the research planner onto a low-capability provider; research strategy cannot bypass connection controls; enabling a feature flag does not authorize an action. Distinguish rollout, mission approval, network admission and evidence.

## O01 — Wrong-layer hardcoding of search provider

- **Original source path:** `backend/services/tools/standalone_actions.py`, handlers `web.research` and `web.search`.
- **Finding:** They directly selected DuckDuckGo **Instant Answer** even though `backend/services/internet/search.py` had a general public-search chain.
- **Architectural impact:** A compatibility/security shortcut inside the handler overrode the provider strategy for **all** public prospect discovery.
- **Correction intent:** Both handlers use the **existing approved provider abstraction**, while each transport satisfies the shared egress contract. Do not replace an unsuitable hardcoded provider with a different hardcoded provider. Provider outcome and selected route must be preserved in evidence.

## O02 — The restriction has identifiable Git history, not an inherent safety justification

The original review reconstructed this lineage:
- **2026-06-26:** Instant Answer nested-topic parsing and response limit expansion.
- **2026-07-27:** general provider search abstraction introduced: Brave, SerpAPI, DDGS and Instant Answer.
- **2026-07-29:** DDGS added as Python dependency.
- **2026-08-21:** separation of raw search hits from verified company identities.
- **2026-10-01:** commit `498d99d3` (via PR #557) changed a `public_search(...)` call to direct `DuckDuckGoInstantAnswerProvider().search(...)`; stated motivation was deterministic compatibility and ungoverned DDGS transport.
- **2026-10-03:** test explicitly pinned the narrower Instant Answer behavior.

**This lineage proves a functional integration regression, not that the old chain was secure or commercially successful.** Reproduce the code history and compare contracts before adopting or rejecting any historical branch.

## O03 — Instant Answer is a different product from general search

The original review independently checked DuckDuckGo's API description and noted that Instant Answer does **not** provide the ordinary web results needed for broad business discovery and may return blank answers for detailed queries.

Three HTTP-successful Instant Answer calls with zero parsed hits **do not establish** that zero suitable Dallas companies exist. They prove only that this endpoint returned no usable Instant Answer material to that parser.

**Required distinction:** endpoint availability, HTTP success, meaningful general-search results, raw candidate URLs and verified company identity are separate facts. Provider fallback should not erase that distinction.

## O04 — DDGS transport governance is a specific integration concern

- **DDGS package provider:** general search exists but uses package-owned HTTP outside `NetworkEgressAuthority`.
- **Instant Answer:** governed HTTP but unsuitable alone for broad discovery.
- **Brave and SerpAPI:** governed HTTP if configured, previously unreachable through normal handler selection.
- **Chromium:** vetted browser navigation/route interception but not ordinary search provider and not automatically chosen for public discovery.

The original recommendation is **neither unrestricted DDGS nor permanent disablement of general search**. Evaluate how each provider can satisfy network destination validation, controlled transport, evidence and optional cost constraints. Network safety remains authoritative for connections; provider selection remains an independent strategy.

## O05 — Hostname text-blocking produces a real-world false positive

- **Original source path:** `backend/services/network_egress.py` checked `BLOCKED_HOST_FRAGMENTS` by substring before DNS.
- **Concrete example in original investigation:** `https://metadata.io/` was rejected because `metadata` matched a banned fragment, despite being a legitimate public B2B business domain.
- **Correct property:** block exact local/reserved destinations, private IPs and DNS answers to forbidden networks; retain HTTPS requirements and connection/DNS pinning. Do not classify a public domain as an internal target solely on English words contained in its hostname.
- **Proof:** controlled DNS responses for a legitimate domain with a blocked-looking token and for a private destination; both positive and negative cases.

## O06 — Browser's declared read-only behavior was not fully enforced

- **Original source path:** `backend/services/internet/browser_session.py`.
- **Finding:** browser action is classified `EXTERNAL_READ`, yet browser clicks and page JavaScript may trigger mutating requests. At the time of the original review, route interception vetted destinations but did not explicitly prohibit POST/PUT/PATCH/DELETE.
- **Evidence limit in original review:** **no successful unauthorized browser write was demonstrated**; this was a source-supported control gap. Mocked browser unit tests did not resolve it.
- **Original posture:** preserve default-disabled Chromium rollout until an actual read-only enforcement proof; do **not** use this concern to prohibit governed general HTTP search.
- **Needed negative test:** actual controlled-server browser interaction proving prohibited request never arrives; also test page navigation, redirects, subresources and the service-worker/WebSocket boundary as appropriate. Method restrictions alone do not guarantee that GET has no effects.

## O07 — Governance, feature rollout and provider strategy were entangled

The original investigation identified:
- `NetworkEgressAuthority`: legitimate destination security responsibility.
- `standalone_actions.py`: inappropriate general-search-provider restriction.
- `capability_resolver.py`: valid mission capability selection, but browser and research path integration incomplete.
- `browser_session.py`: valid feature, network and browser constraints, with observed enforcement gap.
- Ability manifest validation: broad requirement that external actions declare `approval_required=True`, even external reads.
- Catalog: `web.browser_session` is high-risk by default.

**Assessment:** these restrictions are not interchangeable. Distinguish simple public read from external write/outreach and interactive-browser risk without removing human approval where genuinely required. Feature flag is deployment control, not task authority.

## O08 — Provider/evidence data incorrectly describes what happened

The original review identified distinct misstatements in `standalone_actions.py` and downstream artifacts:

| Original observation | Why it matters |
|---|---|
| `source="ddgs"` after Instant Answer actually ran | Source/provider lineage is false |
| `public_search_real=True` after a successful request with zero hits | Provider execution is confused with meaningful discovery |
| `real` largely describes non-fixture execution | It does not prove that any public company was observed |
| `candidates_real` tied to internal/CRM candidates | Genuine public-only candidates may be misrepresented |
| `research_gap=None` when no public hit returned | Absence of evidence is not explicitly represented |
| No provider identity / HTTP status retained per query | Investigators cannot reconstruct search attempt outcomes |

**Correction target:** Record each attempt, its provider, status/error, response class, parsed hit count, raw candidates, identity verification and no-evidence reasons separately. Search hits remain unverified observations until their independent verification path establishes a company identity.

## O09 — Current test strategy can be green without commercially useful discovery

The original investigation reviewed:
- `tests/unit/internet/test_search.py`: two narrow tests, including a mocked Instant Answer response.
- `tests/unit/tools/test_standalone_actions.py`: mocked topical queries (including HubSpot), source partition tests, but not a genuine general web prospect-discovery assertion.
- Live internet proof: accepted an HTTP-successful `real=True` response or successful page read; it did not require actual search hit, actual verified company or positive commercial result.

**Proof required:** distinguish success of transport, positive general search, rejected/verified company and materialized commercial result. Preserve a valid zero-company outcome without inventing contacts or opportunities. Run the queue/lease/dispatcher/evidence path, not just a helper.

## O10 — What remained unknown at original review time

The original author explicitly said: **no new live DDGS or Chromium execution was performed**, no production files changed, and the historical chain's safety and commercial effectiveness had **not** been established. Source behavior, Git history and published endpoint documentation supported the investigation. Any later test result belongs to a subsequent phase, not retroactively to this original review.

## Direct constraints on the rebuild

1. Preserve **existing** network/tenant/approval security boundaries; refine disproportionate restrictions at the responsible owner.
2. Preserve the **existing** provider architecture and distinguish selection from transport permission.
3. Preserve the existing queue, lease, runtime admission and evidence hierarchy.
4. Treat browser readiness and authorization separately from search capability; browser is not an obligatory search fallback.
5. Never equate successful HTTP, a returned URL, verified company identity, and commercial qualification.
6. Preserve the raw-vs-verified identity separation introduced earlier.
7. Do not require new architectural layers; existing roles must cooperate.
8. Require a real general-search outcome and truthful negative/no-hit diagnosis to establish readiness.

## Lineage of later work — **do not conflate with source**

- The **later** engineering handoff introduced **F01–F20** identifiers. They were not assigned in the uploaded original investigation, and their order/content must be compared with that exact later handoff before using as a source of truth.
- The draft PR #634 and its source code are preserved at `5fbc84ab` on `archive/public-research-pr634-5fbc84ab`, but its claims are not proof of original-finding closure.
- **R01–R20** were a further **post-PR source-review** ledger; most of these concerns were **not** stated in the original uploaded investigation. They remain additional adjudication obligations, not retroactively original findings.

This document exists so a second engineer can inspect the original diagnosis without being misled by later, renumbered or expanded analyses.
