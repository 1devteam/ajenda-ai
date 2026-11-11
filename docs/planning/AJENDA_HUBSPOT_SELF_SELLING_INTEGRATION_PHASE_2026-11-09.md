# Ajenda × HubSpot self-selling — formal architecture planning phase

**Phase:** AJ-HS-PLAN-2026-11-09
**Status:** FORMAL PLANNING; NO IMPLEMENTATION, PORTAL MUTATION OR OUTBOUND AUTHORIZATION
**Date:** 2026-11-09
**Pinned implementation baseline:** main at 05e6b12b8a349aaa36e7a9c5d5ad9abd259196c8
**HubSpot observed:** ajenda-ai / portal 246599887 / DEVELOPER_TEST
**Review rule:** Source code, tests, migrations and observed runtime outrank plans and architecture narratives. This phase is not executable proof.

## 1. Purpose and research limitations

Prepare the exact Ajenda-to-HubSpot record/stage/identity integration needed for Ajenda eventually to sell herself, without installing a competing CRM, planner, queue, policy engine, truth store or learning system. This is a document-only adjudication phase. No HubSpot schema, existing records, code, credentials, or runtime state was changed.

Evidence classes: CONFIRMED-CODE means observed directly in the pinned source; CONFIRMED-PORTAL means observed via read-only HubSpot connector; HISTORICAL-PROOF means a dated, documented proof not rerun on this commit; DESIGN-GAP means target exists in design but current implementation was not demonstrated; TEST-REQUIRED means a plausible risk not reproduced or live-proven. Do not conflate these.

Repository tree contained 1,908 entries; relevant source, test, contract, proof, docs and recent PR surfaces were reviewed. A new local test run, GRAFT runtime artifact, live provider action, database inventory, and CI were not executed by this planning inspection. A static trace is not an end-to-end live release attestation.

## 2. Canonical authority and existing execution trace

Ajenda owns tenant-scoped identity, account/contact/opportunity, relationship lifecycle, CRM state, mission composition, qualification, evidence, policy, approval, queue/lease authority, runtime evaluation, and learning. HubSpot is an optional provider projection and observation boundary.

**Existing path**:
1. Outcome interpretation and mission composition select jobs from backend/services/mission_composition/job_catalog.py and versioned contracts in vertical_know_how.py.
2. Governed research, verification, contact observation, sales.research, sales.qualify, and gtm.lead_enrich produce typed prospect, identity, qualification and enrichment artifacts. Missing evidence must remain missing.
3. gtm.email_draft persists a proposed draft and recipient binding; independent review governs any later real send.
4. record.write and backend/services/light_crm/{records,schemas,workflow}.py persist canonical tenant accounts, contacts, opportunities, tasks, relationships and activities, with a read-back path.
5. Optional gtm.crm_upsert calls backend/services/plugins/crm_client.py, resolves a runtime credential, uses existing network egress, calls services/hubspot_crm_adapter/{main,hubspot,models}.py and then reads back HubSpot provider state. Provider identity and verification are returned as evidence, not treated as Ajenda lifecycle truth.
6. The provider-neutral plan_crm_reconciliation path and tools/crm_actions.py create non-authorizing reconciliation plans; current crm.mutate actually writes the INTERNAL record store. This is distinct from the external gtm.crm_upsert path.
7. Optional gtm.email_send has its own outbound channel/approval constraints; real vs simulated effects feed light_crm/workflow.py.
8. Worker/queue/lease, task result, typed artifacts, read models and outcome review independently reconcile runtime and business success. HubSpot connectivity does not authorize a provider effect or imply a sale.

**Existing know-how gates:** REVOPS_V1_KNOW_HOW at revops.research-to-approved-outreach version 1.0.0 is blocked_pending_owner_thresholds. REVOPS_V2_KNOW_HOW at revops.gtm-crm-communications version 2.0.0 is eligible but caps max_external_effects=0, max_prospects=10, max_provider_calls=40, max_wall_seconds=900. V2 eligibility must not be misconstrued as permission for autonomous outreach.

**Sources:** PROJECT_SPEC.md; README.md; AGENTS.md; docs/architecture/SYSTEM_ARCHITECTURE.md; docs/development/GRAFT_PLUS_WORKFLOW.md; docs/planning/GRAFT1ST_UNIVERSAL_CRM_CANONICAL_MAP.md; docs/planning/GRAFT1ST_GTM_CRM_COMMUNICATIONS_CANONICAL_MAP.md; docs/product/GTM_SELF_SELLING_ARCHITECTURE.md; vertical_know_how.py; job_catalog.py; sales and GTM actions.

## 3. Connected HubSpot baseline — read only

HubSpot portal name ajenda-ai, id 246599887, account type DEVELOPER_TEST, USD, timezone US/Eastern, onboarding incomplete. Search totals: CONTACT 2, COMPANY 0, DEAL 0, TICKET 0, NOTE 0, PRODUCT 0, CALL 2, EMAIL 2, TASK 2. Existing contact/call/email/task records are labeled sample data, not evidence of real Ajenda customers. A standalone LEAD search was unsupported by the connector, so do not infer that the provider Lead object is available.

Default deal pipeline ID default: appointmentscheduled, qualifiedtobuy, presentationscheduled, decisionmakerboughtin, contractsent, closedwon, closedlost. The portal's 7 stages do NOT encode Ajenda's 8 opportunity stages. Developer portal custom-pipeline entitlement remains unverified; custom pipeline creation may require a paid tier. Full property-definition queries returned 298 CONTACT, 170 COMPANY and 127 DEAL definitions without an Ajenda-named field surfaced. A missing custom property should still be checked by exact name before any future creation.

Historical Pass 4 documentation records a real contact write with readback, machine self-approval denied and owner approval accepted, but declares provider fault-injection deferred and records proof revision different from this baseline. Current portal identity versus the historical credentialed portal has NOT been verified.

## 4. Canonical record mapping — design decision proposed

| Ajenda canonical object | HubSpot provider object | First-wave direction | Authority / caveat |
| --- | --- | --- | --- |
| account | COMPANY (0-2) | Ajenda projected, provider observed | Ajenda account ID is canonical; domain is supporting evidence |
| contact | CONTACT (0-1) | Ajenda projected, provider observed | Only observed/supplied person facts; email does not own identity |
| opportunity | DEAL (0-3) | Governed Ajenda projection, provider observed | Canonical opportunity ID; never use dealname as primary identity |
| unresolved lead/observation | none | Ajenda only | Adapter currently coerces lead into contact; do not export ambiguous person |
| relationship | Provider associations, later wave | Read then separately governed mutation | Free-text Contact.company is not an association |
| task/activity | Optional later | Ajenda only initially | No dual timeline writer or implicit duplicate tasks |
| draft/consent/suppression/qualification/evidence/knowledge | none wholesale | Ajenda only | Do not leak sensitive business reasoning or delegate approval to CRM fields |

Native field projection: account name/domain/website/phone/description to matching COMPANY properties; observed contact email/firstname/lastname/phone/jobtitle to CONTACT; opportunity name to DEAL.dealname, stage via exact stage-ID map, amount only with known currency and typed format, close date only with approved provider formatting. Provider foreign keys and associations need explicit mapping. Do not copy raw research/evidence/approval material into broadly accessible HubSpot fields.

**Durable mapping requirement:** (Ajenda tenant ID, provider, provider portal/account ID, canonical record type, canonical ID) uniquely identifies an external object type and HubSpot object ID with observation version, last verified effect and merge/unlink history. Ajenda is authoritative. Do not assume cross-tenant equality from matching email or domain. Before adding storage, search existing migrations/repositories and extend the existing canonical owner instead of inventing a second identity store.

## 5. Lifecycle vs opportunity-stage mapping — separate two axes

**Canonical relationship lifecycle**, from backend/services/vertical_ops/crm_reconciliation.py: observed -> resolved -> qualified -> engaging -> opportunity -> customer, with resolved -> disqualified, engaging -> nurture -> engaging, opportunity -> closed_lost, and customer -> expansion. These transitions require Ajenda's evidence and validation, not just the provider stage.

**Canonical opportunity pipeline**, from backend/services/light_crm/schemas.py: new, qualified, discovery, outreach, proposal, negotiation, closed_won, closed_lost. This axis is a sales process, NOT the relationship lifecycle. For example, sending an email is not by itself customer acquisition; Closed Won requires verified commercial outcome.

**Proposed exact development pipeline projection**:

| Ajenda stage | Desired HubSpot label | HubSpot stage ID |
| --- | --- | --- |
| new | New | DISCOVER AFTER APPROVED CREATION |
| qualified | Qualified | DISCOVER AFTER APPROVED CREATION |
| discovery | Discovery | DISCOVER AFTER APPROVED CREATION |
| outreach | Outreach | DISCOVER AFTER APPROVED CREATION |
| proposal | Proposal | DISCOVER AFTER APPROVED CREATION |
| negotiation | Negotiation | DISCOVER AFTER APPROVED CREATION |
| closed_won | Closed Won | Existing closedwon IF retained |
| closed_lost | Closed Lost | Existing closedlost IF retained |

No mapping may invent provider stage IDs. Prefer a separate Ajenda development pipeline only when entitled. Otherwise, obtain distinct approval and complete rollback/consumer analysis before changing the currently empty default pipeline. Do not perform lossy mapping or bidirectional stage changes while 7 provider stages cannot represent 8 canonical stages. Stage probabilities need owner-approved commercial definitions, not guessed model scores.

Unmapped, removed or renamed stage: explicit UNMAPPED blocker; no silent write. Provider change/conflict: observe -> compare -> proposal -> separately authorized mutation -> readback; never automatically promote HubSpot to canonical lifecycle. Version map by portal + pipeline ID + schema version. No provider stage alone grants consent, an outreach decision, Closed Won, or customer status.

## 6. Issue ledger: code evidence, impact, possible fix and test

Each item is UNRESOLVED until confirmed against an executed proof and deliberately dispositioned. A candidate repair is not an instruction to implement without UPG/LAP/GRAFT adjudication.

| ID | Priority | Class | Observed implementation issue / potential failure | Owner-specific possible correction and proof |
| --- | --- | --- | --- | --- |
| HS-01 | P0 | CONFIRMED-CODE | HubSpot _find_existing_id takes the first matching search hit. COMPANY falls back to name and DEAL to dealname; collisions can target the wrong entity. | Canonical tenant+portal+record link, uniqueness and ambiguous-match blocking; duplicate company/deal tests. |
| HS-02 | P0 | CONFIRMED-CODE | Adapter receives idempotency key but main.py ignores it; provider-side CRM v3 does not guarantee idempotency. Identity-based lookup cannot handle concurrent creates or post-write timeouts safely. | Durable effect claim/ledger and replay/readback reconciliation; parallel create, worker restart and timeout-after-write proof. |
| HS-03 | P0 | CONFIRMED-CODE | External gtm.crm_upsert does not consume the generic CRMReconciliationPlan while crm.mutate currently writes internal records. | Route provider writes through existing identity/reconciliation/authority ownership without a parallel executor; version/authorization proofs. |
| HS-04 | P0 | CONFIRMED-CODE | Provider allowlist drops unknown Ajenda fields and GET readback requests only fixed standard fields. New custom fields would be inert without adapter change. | Typed, versioned provider projector, allowlist, explicit rejected-required-field behavior and exact readback; custom-field tests. |
| HS-05 | P0 | CONFIRMED-CODE + PORTAL | Ajenda has eight stage codes; HubSpot default has seven incompatible stage IDs; no exact bridge mapping exists in adapter. | Approve portal pipeline strategy and implement exact versioned mapping; unknown stage blocks, full matrix tests. |
| HS-06 | P0 | CONFIRMED-CODE | HubSpot RECORD_TYPE_TO_OBJECT converts lead into contacts, potentially treating unresolved signals as real people. | Only export resolved/verified contacts, retain unresolved lead evidence in Ajenda; no invented contact proof. |
| HS-07 | P0 | CONFIRMED-CODE | on_email_sent can move an opportunity to outreach without examining sent_real; email handler invokes hook for simulated send status too. | Separate simulation from verified commercial effects, disallow simulated stage advancement; mock, simulated, real-send regression. |
| HS-08 | P1 | CONFIRMED-CODE | Adapter searches at most 25 provider results, does not paginate, and selects first identity result. | Bounded pagination with explicit too-many/ambiguous handling; >25 results tests. |
| HS-09 | P1 | CONFIRMED-CODE | Related HubSpot contacts are looked up via free-text company CONTAINS_TOKEN rather than provider association IDs. | Association API read+write with exact parent/company binding and verified readback; same-name company tests. |
| HS-10 | P1 | CONFIRMED-CODE / TEST-REQUIRED | All allowlisted properties are stringified, with no typed per-field mutation protocol for currency/amount/dates/null clearing. | Typed projection and inverse readback normalization; boundary tests. |
| HS-11 | P1 | CONFIRMED-CODE / TEST-REQUIRED | crm.observe infers lifecycle from lifecycle_state or stage; many opportunity stages are not CRMLifecycleState enum values. | Two explicit axes with independent schema checks and transition tests. |
| HS-12 | P1 | CONFIRMED-CODE / TEST-REQUIRED | crm.verify_effect compares receipt.provider_account_id to Ajenda tenant ID; appropriate for internal receipt, not a HubSpot portal ID. | Verified tenant→portal link contract and separate internal/external receipt paths; cross-tenant/portal proof. |
| HS-13 | P1 | CONFIRMED-CODE / TEST-REQUIRED | sales.research and StandardCrmClient can intentionally fall back to internal CRM after external error; hybrid output may be consumed as provider quality if provenance lost. | Preserve external_attempt_failed, source and hybrid_mode through composition/read model; fail when provider explicitly required. |
| HS-14 | P1 | DESIGN-GAP | No active canonical HubSpot identity-link persistence path established by this trace despite future-state design. | Full repository/migration owner audit, then extend one Ajenda-owned durable mapping store only if actually missing. |
| HS-15 | P1 | CONFIRMED-CODE | RevOps V1 blocked pending thresholds, V2 eligible but max_external_effects=0. No complete autonomous send cycle is authorized by know-how. | Keep zero-effect pilot; require approved thresholds, communication policy and live proof before budget changes. |
| HS-16 | P1 | HISTORICAL-PROOF / TEST-REQUIRED | Pass 4 explicitly deferred provider fault injection, and current portal/commit are not the historical proven environment. | Fresh credentialed exact-revision proof, timeout/5xx, ambiguous effect, review, queue/lease, effect receipt and readback. |
| HS-17 | P1 | CONFIRMED-CODE / TEST-REQUIRED | gtm.crm_upsert overlays inp.data onto every qualified row and dedupes using first identity key; mistaken global overlay can modify multiple records. | Schema-bound per-row immutable identity and scoped overlays; multi-prospect conflicting identity regression. |
| HS-18 | P1 | CONFIRMED-CODE / TEST-REQUIRED | Internal opportunity upsert can reuse the first matching contact_id when no opportunity ID supplied; a contact may own multiple opportunities. | Require stable opportunity identity for external projection; multiple-deals-per-contact tests. |
| HS-19 | P1 | CONFIRMED-PORTAL / TEST-REQUIRED | Developer portal sample records only, onboarding incomplete, and historical provider-account continuity unverified. | Verify exact connected credential/portal relation without exposing secret; synthetic scoped proof not production import. |
| HS-20 | P2 | DESIGN-GAP | Provider synchronization for tasks, activities, attribution, association history and consent was not end-to-end proven. | Defer optional projections until primary identity/write proof; data-minimization and authority review. |
| HS-21 | P1 | CONFIRMED-CODE / TEST-REQUIRED | SMTP path has a durable send claim; Gmail API send branch's equivalent replay-safety mechanism was not established by inspection. | End-to-end transport-specific replay/ambiguous-send proof before enabling nonzero send budgets. |
| HS-22 | P1 | CONFIRMED-CODE | light_crm/schemas.py normalize_stage allows noncanonical unknown strings after normalization despite PIPELINE_STAGES list. | Enforce allowed stage vocabulary at canonical mutation owner after compatibility impact review. |

The priority is impact if deployed, not proof of exploitation. HS-11, 12, 13, 14, 16, 17, 18 and 21 require deeper executor tests before being called reproduced runtime defects. Never inflate the ledger by presenting a suspicion as a confirmed incident.

## 7. HubSpot custom-property adjudication

**New fields necessary immediately: ZERO.** Standard HubSpot properties already provide name, domain, email, dealname, dealstage and pipeline. First establish stable canonical-provider linking and mapping; a property does nothing until code projects, reads and verifies it.

**Conditional minimal proposal:** exactly one opaque short text field named ajenda_entity_key on each of COMPANY, CONTACT and DEAL (three schema definitions, same name in separate object types). Value derived from an opaque deterministic Ajenda tenant+canonical record identity; no plaintext email, contact detail, research hypothesis or secret. Must be indexed/searchable as needed by proven provider capability, not presumed unique. Ajenda's mapping store enforces uniqueness; HubSpot key is recovery/readback aid. Requires explicit property-creation approval, exact schema + provider entitlement, adapter allowlist and typed readback changes.

**Reject as default custom fields:** qualification_confidence, business_need_hypothesis, consent_status, authorization_status, learning_reference, research_reference, approval_granted. Their canonical semantics and review evidence live inside Ajenda and a writable provider property must not become an approval switch.

## 8. UPG/LAP/GRAFT+ ownership, blast radius and invariants

Potential future affected code paths (NO files modified yet):
- Composition: mission_composition/job_catalog.py, action_input_sales.py, action_input_communications.py, vertical_know_how.py, binder, artifact schemas, completion/deliverable.
- Canonical: light_crm/schemas.py, records.py, workflow.py, tools/crm_actions.py, vertical_ops/crm_reconciliation.py, tenant repositories and possibly migrations.
- External effect: plugins/crm_client.py, tools/gtm_action_crm.py, services/hubspot_crm_adapter/{main,hubspot,models}.py, credentials, network egress, manifests, ExecutionCoordinator, task grants, queue and worker.
- Communications/learning: tools/gtm_action_email.py, communication_policy.py, deliverable approvals/receipts, outcome review and knowledge proposals.

Before any implementation, run build_dependency_graph.py, graph_impact_analysis.py and graph_proof_selection.py on exact affected files with scope/risk and proof report. UPG/LAP must identify source of truth, dependency, tenant and side-effect boundaries, failure/retry/compensation, concurrency, downstream consumer and proof obligations. Preserve no second runtime/policy engine; tenant isolation; queue+lease authority; independent payload-bound review; no synthetic business success; explicit effect certainty; provider readback; evidence lineage; rollback.

## 9. Phases and release gates

P0 — PLANNING: accept this ledger and two-axis mapping, settle business thresholds and owner decisions; no effects.
P1 — CANONICAL IDENTITY: find existing mapping owner before any schema, ensure provider link conflict/version and multiple-opportunity support; deterministic no-provider tests.
P2 — PORTAL CONTRACT: discover pipeline/schema entitlement and exact stage IDs. Propose separately approved new Ajenda pipeline or default edit, retaining rollback; verify all eight stages.
P3 — PROVIDER PROJECTION: implement versioned typed mapping, associations if required, bounded search, explicit required/optional property rules; tests for duplicates/unknown fields.
P4 — GOVERNED RECONCILIATION: integrate with existing runtime authority and readback/effect ledger; controlled 429/5xx, concurrent retry, stale version, timeout-after-effect, cross-tenant and portal proof.
P5 — SYNTHETIC SELLING: exact-revision, zero-live-send Ajenda mission research → qualify → internal CRM → draft → approval → governed HubSpot projection/readback → deliverable/acceptance; review actual durable artifacts. Sample contacts remain samples.
P6 — OUTBOUND/LEARNING: only after transport, consent/suppression/cadence, recipient provenance, policy, grant and real-vs-simulated proofs; later nonzero external-effect budget requires owner authorization.
P7 — RELEASE: targeted+graph-selected+full tests; contract, runtime-authority, migration, GRAFT reconciliation, isolated Compose and separately credentialed provider proof. Record failed/skipped checks and never claim runtime readiness from plan alone.

**Failure matrix:** two same-name companies; two same-name deals; missing email; 2 opportunities per contact; different Ajenda tenants and portals; parallel creates; timeout after successful write; 429/5xx; stale record; unknown stage; malformed amount/date; simulated send; draft rejected; grant expired/altered; credential revoked midmission; valid-empty prospect discovery; provider readback mismatch; proof replay with no new effect. Each must produce a durable correct result, conflict or explicit blocker, not hidden success.

## 10. Open questions, decisions and exit criteria

D1: Is connected portal 246599887 the intended disposable proof portal and the historical Pass 4 credential target? Unverified.
D2: Is additional custom deal pipeline available on this developer account? Unverified; no default pipeline edit without separate approval.
D3: What approved deal-stage forecast probabilities and prospect thresholds apply? Owner input, not inferred.
D4: Where will the durable provider identity relation live? Audit migrations/repositories first.
D5: Will initial HubSpot synchronization be one-direction Ajenda→HubSpot with observation back? **Proposed yes**; unapproved external edits do not change canonical identity/lifecycle.
D6: Any real outbound email, calls or publication? **No during this phase**. Separate authority and live proof later.

Planning exit: owner-reviewed canonical mapping and issue dispositions; explicit change/portal decisions; pinned implementation work packages and tests. Implementation exit: real source, migration, runtime, provider evidence and current CI on exact commit. This document authorizes none of those actions.

## 11. Evidence source register

Full code/contract files reviewed or traced:
- AGENTS.md; PROJECT_SPEC.md; README.md; docs/architecture/SYSTEM_ARCHITECTURE.md; docs/development/GRAFT_PLUS_WORKFLOW.md
- docs/planning/GRAFT1ST_UNIVERSAL_CRM_CANONICAL_MAP.md; docs/planning/GRAFT1ST_GTM_CRM_COMMUNICATIONS_CANONICAL_MAP.md; docs/planning/VR01_REVENUE_OPERATIONS_BASELINE.md
- docs/product/GTM_SELF_SELLING_ARCHITECTURE.md; docs/policies/OUTBOUND_COMMUNICATION_POLICY.md; docs/architecture/INTERNAL_CRM_COMPLETION_MAP.md
- backend/services/light_crm/{schemas,records,workflow}.py; backend/services/tools/{sales_action_research,sales_action_qualification,sales_action_records,sales_action_followup,gtm_action_crm,gtm_action_drafts,gtm_action_email,gtm_action_lead,crm_actions}.py
- backend/services/plugins/crm_client.py; backend/services/vertical_ops/{crm_reconciliation,communication_policy}.py; backend/services/mission_composition/{job_catalog,action_input_sales,action_input_communications,vertical_know_how,revops_deliverable_prospects,revops_deliverable_approval,revops_deliverable_effects}.py
- services/hubspot_crm_adapter/{hubspot,main,models}.py
- tests/unit/adapters/test_hubspot_crm_adapter.py; tests/unit/plugins/test_crm_client.py; tests/unit/services/{test_crm_reconciliation,test_communication_policy,test_light_crm}.py; tests/unit/tools/test_gtm_crm_pipeline_artifacts.py
- tests/integration/credentials/{test_hubspot_credential_flow_real,test_hubspot_credential_api_invoke_real}.py
- docs/validation/{pass3-internal-crm-closure-2026-10-07,pass4-hubspot-provider-lane-closure-2026-10-07}.md; docs/audits/public-research-rebuild/09-IMPLEMENTATION-CLOSURE-AND-OPEN-PROOF.md
- Recent merged PR #657 (governed self-selling research/draft), #663 (intelligence evidence), #664 (HubSpot adapter base security), #666 (disposable proof credentials).

**Historical proof is not current proof.** No running production state, runtime test, test database or HubSpot write was inspected or changed in this document-only phase.
