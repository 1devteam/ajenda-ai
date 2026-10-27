# Independent defect ledger — public research, candidate truth, governance

Baseline for new work: `main` at creation of `rebuild/public-research-evidence-first`.
Historical PR #634 patch: `5fbc84ab5b46f7cc6358f842f55a77072efedffb`.
This ledger describes independently traced source behavior, not acceptance of Codex's original remediation claims. `Observed in source` does not mean a complete PostgreSQL/Redis/browser reproduction was executed by this reviewer.

## Original F01–F20 preservation

Do **not** discard original F01–F20 simply because PR #634 once listed them resolved. They remain separately accountable:

- F01/F02: web.research and web.search directly select Instant Answer instead of effective general search.
- F03/F07: package-owned DDGS transport lacks proof of shared egress policy.
- F04/F05: existing general provider chain disconnected; Instant Answer success not equivalent to general discovery.
- F06: irrelevant hardcoded `local contractor` search query.
- F08/F15: arbitrary hostname substring blocking and provider/source attribution.
- F09/F16: semantics of real/fixture, public observed, counts, provider attempts, and no evidence.
- F10–F14: Playwright built but runtime usability and method/origin/WS/service-worker/redirect protections require proof.
- F17–F19: raw hit versus verified identity, seed/qualification truth, empty producer/binder/terminal-contract semantics.
- F20: deterministic tests and opt-in real end-to-end proof should establish commercial observation, not just provider HTTP response.

Numbering above matches the earlier engineering discussion only approximately; use the original PR's exact F01–F20 table and associated code/commit evidence when adjudicating individual entries.

## Prioritized confirmed source defects and proof obligations

| ID | Severity | Origin relative to PR #634 | Root code path and mechanism | Mandatory negative/positive evidence |
|---|---|---|---|---|
| R01 | BLOCK | New interaction between PR empty-path and pre-existing seed | `action_input_sales.py` synthesizes `lead=HVAC (Dallas)`; `sales_action_qualification.py:160-163` turns seed into `prospects_in` whenever bound prospects are empty. Valid zero-result search can yield a scored invented company and overwrite upstream gap. | Real composed empty mission => scored=[], qualified=[], original gap retained; explicit named-company input remains supported. |
| R02 | BLOCK | PR fix incomplete | `sales_action_qualification.py:173-180` still `lead.setdefault` merges composition lead `industry/location/source` onto first verified prospect. New unit test does not include the actual seed. | First/second real candidates lacking observations remain free of target facts; eligibility/score not inflated by mission metadata. |
| R03 | BLOCK | Pre-existing, newly exposed by general discovery | `page_read.py` returns `real=True` for 4xx/5xx; `web_action_contacts.py` uses `snapshot.real` and lexical matches for identity. | 403/404/503 never verify a company; HTTP 200 valid page retains evidence. |
| R04 | BLOCK | Pre-existing, newly exposed | `standalone_actions._prospect_from_web_result` derives `domain` from search URL, then `web_action_contacts.py:397-425` calls same-host match an official source and accepts weak name/location/industry tokens. | Third-party non-blacklisted landing page must not verify purported company; true official company verified; ambiguous cases remain unverified. |
| R05 | HIGH | Pre-existing | `action_input_research.py` uses `entity.name or industry` for `company`; normal HVAC market scope yields company='HVAC'. | Distinguish named company, industry-only category and CRM scope; never emit market category as verified company. |
| R06 | HIGH | Pre-existing | `web_action_contacts.py` adds `kind=None, value=None, real=True` as observed contact for verified page without contact, counts URL to reach `accept_met`. | No contact => contact collection unmet, company verified retained; real phone/email => met. |
| R07 | HIGH | Pre-existing | `web_action_identity_policy.py` excludes industry tokens <4 chars; `web_action_contacts.py` excludes location tokens <3 chars and substitutes Dallas/DFW/Texas if none; AI/IT/HR/3PL + LA/NY/SF cannot be honestly classified. | Short named industries and cities plus true absent location work; no implicit Dallas; negative out-of-market pages rejected. |
| R08 | HIGH | Pre-existing | `standalone_actions.py:540-565` deduplicates raw public candidates by company/title, potentially discarding a valid official URL after a directory hit with the same title. | Same title different URLs may both be observed, while true duplicate URLs dedupe. |
| R09 | HIGH | Pre-existing; PR's new search relies on it | `network_egress.py:175-194` eagerly downloads and decodes entire response before slicing to `response_text_limit`. | Streaming bounded bytes/decoded payload on multi-MB response; no unbounded worker memory. |
| R10 | HIGH | Pre-existing | `network_egress._connect_url_for_pinned_ip` retains parsed username/password in network URL; generic `http.request` only rejects raw sensitive headers, not userinfo; HTTPX can synthesize Basic auth. | Reject userinfo and credentialed query for public reads at actual shared boundary while preserving explicitly authorized credential APIs. |
| R11 | HIGH | Pre-existing; browser expanded in PR | `browser_session._allowed_hosts` reduces allowed_origins to hostname, not HTTPS origin (host + port). | `https://site:443` allow does not authorize `https://site:8443`; redirect/frame requests enforce same policy. |
| R12 | HIGH | PR new configuration | `search.py` configured `ddgs` silently selects HTML/Instant, rather than failing or clearly aliasing. | Explicit setting auditable and operator-visible. |
| R13 | HIGH | PR new HTML search | HTTP 200 challenge/unrecognized HTML creates `SearchBundle(real=True, results=[])`; `standalone_actions` records empty candidate URLs as though general search completed. | Distinguish known valid no-result HTML from CAPTCHA/challenge/malformed markup/provider errors; preserve provider attempts. |
| R14 | HIGH | PR search behavior | HTML rate limit/failure followed by Instant Answer HTTP 200 empty loses the crucial distinction general web search unavailable vs no matching companies. | Separate provider failure and no-results; no false market conclusion. |
| R15 | HIGH | PR incomplete provenance | `standalone_actions.web_search` doesn't emit provider attempts and always labels top-level `source=ajenda_brain`, even public-only results. | Test provider lineage and public/internal partitions in both web.search and web.research. |
| R16 | HIGH | PR new empty binding gate | `mission_input_binding._completed_empty_public_research_source` requires only whitelisted action + nonempty research_gap; then unsets binding_required when resulting prospects empty. | Wrong/missing/malformed bound output cannot clear required binding; completed genuine no-result with declared provenance can. |
| R17 | HIGH | PR unproven end-user semantics | `deliverable_runtime_artifacts.py` extracts list payload; reason `research_gap` is sibling output, not represented by empty list. | Fresh-session operator deliverable readback states original no-evidence cause without manual task metadata inspection; commercial acceptance remains unmet as appropriate. |
| R18 | HIGH | PR test gap | Unit browser method guard tests use mocks; no controlled-server real Chromium POST rejection/port-confusion proof; live `example.com` test is positive navigation only. | Real browser prohibited write blocked before server; service worker, WebSocket, download isolation; authorized page still readable. |
| R19 | HIGH | PR test gap | Opt-in Dallas HVAC integration test accepts `verified=[]` and `qualified=[]` and overrides route authorization; green CI premerge proof is generic operator workflow. | Real general search result -> actual page -> defensible verified identity -> qualified/rejected with reasons -> durable readback. Preserve empty and denied proof separately. |
| R20 | MEDIUM | Pre-existing | `network_egress.py` blocks any embedded `.local.` label even within public `*.example.com`; suffix `.local` should remain prohibited. | Public `x.local.example.com` resolved to public IP passes, `x.local` and private IP remain blocked. |

## Acceptance invariants that cannot be weakened

1. No raw search hit becomes a verified company solely through same-URL matching, loose lexemes, or a directory blacklist.
2. Mission market scope never becomes an individual verified company's field, signal, urgency, or intent by fallback.
3. A true empty search produces zero fake scored/qualified company rows.
4. No results, provider inaccessible, invalid upstream, and all candidates rejected are separate durable outcomes.
5. Zero qualified companies does not satisfy a requested commercial deliverable quantity; operational completion must remain distinct.
6. No permission, tenant, network, DNS, browser write, contact collection, or CRM authority bypass for convenience.
7. Existing internal CRM-only workflows remain behaviorally compatible.

## Required evidence for each finding

- First reproduce the failure (isolated deterministic test or controlled execution).
- Identify the correct pre-existing owner and consumers.
- Repair at that owner, not via an additive compatibility exception.
- Confirm the regression turns green alongside adjacent negative tests.
- Integrate positive and empty live proof through the same queue/lease/dispatcher/persistence spine.
- Record disposition as confirmed/repaired, disproved with proof, partially confirmed, or unresolved. No claims of broad closure by green CI alone.

Independent source review links remain with PR #634; exact snapshot remains archived. This ledger establishes scope of proof, not an instruction to blindly implement any speculative edge case.
