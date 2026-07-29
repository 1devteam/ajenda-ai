# Codebase gap audit (breakage / drift / stubs)

**Status:** Living notes  
**Last reviewed:** 2026-07-29  
**Branch sampled:** `fix/connector-read-fidelity-and-ddgs` (@ `09511df`) + main after #391  
**Method:** Code search + composition resolver probes + registry/manifest cross-check. Not a full security audit.

Use this file as the backlog map before more mission testing. Prefer implementation evidence over docs.

---

## Pass 1 — summary (prior session)

### Critical / high

| ID | Finding | Location | Risk |
|----|---------|----------|------|
| C1 | External reads **complete as simulated** without credentials | `gtm_actions`, `google_calendar_actions`, `salesforce_actions`, `linkedin_actions`, `github_actions` | Task `completed` with fake world state |
| C2 | **Calendar composition ready without Google** | `ops.calendar_briefing` `credential_policy=optional`; prefers `google_calendar.events_read` | Ready → runtime simulated events |
| C3 | Dual calendar stacks | `GoogleCalendarProvider` (NotImplemented) vs `google_calendar_actions` (live/sim); `calendar.read` local only | Drift / wrong provider |
| C4 | Uncredentialed **lead enrich invents contacts** | `gtm.lead_enrich` local sim path | Downstream drafts look real |
| C5 | SERP → prospect has **no quality gate** | `web.research` / standalone research | Wrong geo, self-hits, listicles still “success” |

### Medium stubs / placeholders

| ID | Finding | Location |
|----|---------|----------|
| M1 | Composition placeholders | `pending.binding@invalid.local`, `pending.binding.company` in `action_inputs.py` |
| M2 | `http.request` default `https://example.com` | `action_inputs.py` |
| M3 | Draft defaults `lead@example.com` | `schemas.py`, `draft_generation.py` (send path blocks most of these) |
| M4 | Accounting jobs catalog-only; `vertical.finance.sync_revenue` **not registered** | `job_catalog.py` |
| M5 | Deferred connector ops | Calendar write, Contacts write, LinkedIn publish |

### Drift

| ID | Finding |
|----|---------|
| D1 | Job catalog candidates vs ActionRegistry (finance sync missing) |
| D2 | FE kitchen-sink `missionAbilities` vs composition-owned graphs |
| D3 | Live deploy tree often dirty vs git tip |
| D4 | HubSpot ingress container restart loop in local env |

### Architecture gaps (product)

| ID | Finding |
|----|---------|
| A1 | NL “school” instead of plugin/catalog linking |
| A2 | No mission kinds (self / CRM list / calendar / draft / GTM) |
| A3 | Hostile roofing restatement template |
| A4 | Confirmed intent not fully frozen at execute |
| A5 | HubSpot list/deals not true adapter shapes |
| A6 | Gmail summarize ≠ message body fetch |

### Solid enough (do not over-correct)

- Send binding fail-closed for placeholder/sim recipients  
- Salesforce SOQL job: connection required  
- HubSpot-source research (on #392 tip): CRM-bound + connection required  
- Charter FE/BE contract test when run  
- Live runtime proof covers queue/worker/lease/audit/enrich/brain slice  

---

## Pass 2 — deeper findings (this pass)

### Composition readiness matrix (no credentials)

Probed `evaluate_action_candidate` for each job’s **first preferred action** with empty integrations:

| Job | credential_policy | First action | No-cred result | Verdict |
|-----|-------------------|--------------|----------------|---------|
| `research.discover_prospects` | optional | `web.research` | ready | OK (public search intentional) |
| `sales.research_context` | optional | `sales.research` | ready | OK for hybrid brain; **not** fail-closed for CRM-only intent |
| `sales.qualify_prospects` | none | `sales.qualify` | ready | OK (local) |
| `gtm.enrich_contacts` | none | `gtm.lead_enrich` | ready | **Gap:** local sim contacts (C4) |
| `email.prepare_outreach` | none | `gtm.email_draft` | ready | OK if binding_required |
| `email.deliver_outreach` | required | `gtm.email_send` | charter_blocked (default never_do) | OK default |
| `email.read_messages` | required | `gtm.email_check` | connection_required | OK composition; **runtime still can sim if invoked unbound** |
| `crm.read_records` | required | `sales.research` | connection_required | OK composition |
| `crm.query_salesforce` | required | `salesforce.soql_read` | connection_required | OK composition; **runtime sims if unbound** |
| `crm.pipeline_maintenance` | **optional** | `gtm.crm_upsert` | **ready** without HubSpot | **FAIL-OPEN** (P2-new) |
| `ops.calendar_briefing` | **optional** | `google_calendar.events_read` | **ready** without Google | **FAIL-OPEN** (C2 confirmed) |
| `gtm.publish_content` | required | `gtm.social_publish` | charter_blocked (default never_do) | OK default; sim path if charter allows |
| accounting.* | catalog_only | — | not runtime | Stub catalog |

**Rule exposed by pass 2:**  
`credential_policy=optional` + connection **hint** present ⇒ action can be **ready** without connection, then **runtime simulates**. Composition “will not simulate” only applies when policy is `required`.

### External side-effect actions in registry

Registered external (or elevated) actions:

- **external_read:** `github.repo_read`, `google_calendar.events_read`, `gtm.email_check`, `http.request`, `linkedin.profile_read`, `provider.external_read`, `salesforce.soql_read`, `web.browser_session`, `web.page_read`, `web.search`
- **external_write:** `web.open_write`
- **external_send:** `gtm.email_send`, `webhook.dispatch`
- **external_publish:** `gtm.social_publish`

Several external_read handlers still implement uncredentialed **simulated complete** (C1). Composition gating is incomplete for optional-connection jobs.

### Registry / catalog hygiene (pass 2 numbers)

| Set | Count / notes |
|-----|----------------|
| Registered actions | ~37 |
| Ability manifests | ~34 |
| Job catalog candidates | ~22 |
| In jobs, not registered | `vertical.finance.sync_revenue` (catalog_only only) |
| Job candidate without clean manifest | `crm.research` (alias-ish) |

### Silent exception swallows

| Location | Behavior |
|----------|----------|
| `proposal_store.py` | Multiple `except Exception: return None/False` — DB failure can hide durable proposal writes (documented fail-closed for escalation, but callers may assume success) |
| `service._connected_sets` | `except Exception: return empty sets` — credential listing failure looks like “no connections” (fail-closed-ish) not hard error |
| Worker loops | Broad `except Exception` with logging — OK if always logged; verify no path marks task completed after swallowed tool error |

### Binding layer (good, with gaps)

- `mission_input_binding` **does** fail closed when `binding_required` and no upstream prospects/drafts.  
- Send path refuses `@invalid.local` / `@example.com` / simulated contacts.  
- **Gap:** enrich/draft can still **complete** earlier with sim/placeholder data; only send is strict. Qualify/draft may look “done” with garbage world-state.

### Placeholder inventory (production composition)

| Token | Use |
|-------|-----|
| `pending.binding@invalid.local` | Draft/send recipient until bind |
| `pending.binding.company` | CRM upsert company until bind |
| `https://example.com` | `http.request` default URL |
| `lead@example.com` | Schema/draft defaults |
| Simulated GCal/LinkedIn/GitHub/Salesforce payloads | Uncredentialed external_read |

### Deploy / ops (pass 2)

| Finding | Notes |
|---------|-------|
| Live proof script rebuilds full compose (incl. Prometheus) | Long; can recreate volumes depending on flags — operators should know |
| Dirty live git tree vs worktree tip | Risk of “main” image that is neither main nor PR |
| HubSpot ingress restart | Breaks real CRM ingress lane even when composition is ready |

---

## Unified priority backlog (fill order)

### P0 — stop lying “ready/completed”

1. **Calendar:** `ops.calendar_briefing.credential_policy = required`; never ready without Google; never sim when connection was required.  
2. **Global rule:** If composition selected an action with `requires_connection` / external credential reference expected, **runtime fail** without cred — no simulated complete.  
3. **CRM upsert optional job:** either require HubSpot for `gtm.crm_upsert` when selected, or do not prefer external upsert without connection.

### P1 — truthfulness of research & enrich

4. SERP quality gate for prospect mode.  
5. `gtm.lead_enrich`: no silent sim contacts when mission expects real enrich (or mark output non-real and block qualify/draft bind).  
6. Freeze confirmed composition instruction/intent at execute.

### P2 — product completeness (plugin linking)

7. Mission kinds + connector-native short missions (HubSpot list, calendar, self-profile, draft-only).  
8. Kill roofing-only restatement template; restatement per kind.  
9. True HubSpot list/deals APIs; Gmail body/summarize path.

### P3 — hygiene

10. Remove or implement `vertical.finance.sync_revenue` / accounting catalog-only jobs.  
11. Collapse dual Google Calendar provider shells.  
12. Deploy only from clean git SHAs.  
13. Stabilize HubSpot ingress in local/prod-like compose.

---

## Suggested verification after each fix cluster

```bash
# Narrow
pytest tests/unit/services/test_ability_connector_vocab.py \
  tests/unit/services/test_mission_composition_engine.py \
  tests/unit/tools/ -q

# Composition connection matrix smoke (extend as tests)
# Calendar without creds must not be ready
# CRM upsert without HubSpot must not be ready if selected for external path

# Full
bash deploy/scripts/live-runtime-proof.sh
```

Add unit tests that assert:

- `ops.calendar_briefing` + no integrations → not ready / connection_required  
- External action with missing cred + composition credential_reference → handler raises, task fails (not completed sim)

---

## Explicit non-goals of this audit

- Full threat model / authz review  
- Full migration/data-plane audit  
- Proving every ability end-to-end against live third parties  

---

## Remediation log

| Date | Change |
|------|--------|
| 2026-07-29 | **P0 composition:** any action with a connection hint is `connection_required` without that connection (stops calendar/CRM upsert fail-open). |
| 2026-07-29 | **P0 calendar job:** `ops.calendar_briefing` → `credential_policy=required`, candidates only `google_calendar.events_read`. |
| 2026-07-29 | **P0 runtime:** `external_sim_policy.require_external_secret` — Google Calendar, Salesforce, LinkedIn, GitHub, Gmail check **fail** without credential unless `AJENDA_ALLOW_SIMULATED_EXTERNAL=1`. |
| 2026-07-29 | Unit tests updated for fail-closed default + explicit sim-allow path. |
| 2026-07-29 | Shell: `AJENDA NAV v2` block in `~/.zshrc` (`ajhelp`, `ajw`, `ajrebuild`, `ajgate`, `ajsync`, …). |

## Changelog

| Date | Note |
|------|------|
| 2026-07-29 | Pass 1 noted from session audit |
| 2026-07-29 | Pass 2: readiness matrix, external SE inventory, silent excepts, binding gaps, backlog ordered |
| 2026-07-29 | P0 fail-closed fixes landed on `fix/connector-read-fidelity-and-ddgs`; notes + zsh nav |
