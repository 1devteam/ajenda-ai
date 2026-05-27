# AJENDA-AI GTM Self-Selling Architecture

**Status:** Planned (Bundle 6.1 contract baseline)  
**Effective date:** May 27, 2026  
**Owner:** Product/Architecture + Security/Governance  
**Last reviewed:** May 27, 2026  
**Source-of-truth precedence:** Implementation/tests/runtime proof > PROJECT_SPEC.md > architecture docs

---

## 1) Purpose

This document defines the contract architecture for AJENDA-AI GTM self-selling missions.
It introduces GTM mission families, control boundaries, and activation rules without granting implicit execution authority.

Bundle 6.1 is documentation-only and establishes policy-safe foundations for later gated implementation bundles.

---

## 2) Scope and non-goals

### In scope

- GTM mission-family taxonomy.
- Stage-by-stage contract for self-selling mission flows.
- Authority mapping for GTM artifacts and runtime actions.
- Policy gating model for outbound and publishing actions.
- Evidence and observability requirements for GTM execution.

### Out of scope (until later bundles)

- Autonomous outbound publishing that bypasses human/policy gate.
- Direct runtime execution from capability declaration or adapter metadata.
- Ungoverned cross-tenant lead operations.
- Hidden orchestration paths that skip queue + lease authority.

---

## 3) Architecture principles

1. **Declarative GTM contracts remain non-executable by default.**
2. **Runtime execution remains queue-authoritative and lease-governed.**
3. **Outbound actions are policy-gated and fail-closed.**
4. **High-risk GTM actions require explicit approval checkpoints.**
5. **All GTM mission state transitions must produce reviewable evidence.**

---

## 4) GTM mission-family contract model

Mission families are product-level contracts and not implicit runtime permissions.

### Family A — Lead discovery and qualification

Objective: identify and qualify target accounts or contacts.

Expected stages:

1. audience definition
2. candidate discovery
3. enrichment and validation
4. qualification scoring
5. review-ready lead packet generation

High-risk boundary: false attribution, privacy misuse, and non-compliant data sourcing.

### Family B — Outbound sequencing and follow-up

Objective: produce and route outbound communication drafts and controlled send plans.

Expected stages:

1. persona + offer fit analysis
2. channel strategy selection
3. message draft generation
4. policy and brand risk screening
5. approval routing
6. controlled dispatch (only after explicit gate)

High-risk boundary: unauthorized contact, policy-unsafe claims, and non-compliant timing/frequency.

### Family C — Social/blog content pipeline

Objective: create channel-specific, attributable content artifacts.

Expected stages:

1. theme and campaign objective selection
2. research and source grounding
3. draft generation
4. quality/relevance/compliance screening
5. approval and scheduling
6. publish execution (gated)

High-risk boundary: unsourced claims, brand damage, and policy violations in published content.

### Family D — Attribution and conversion evidence

Objective: record and evaluate campaign outcomes and conversion pathways.

Expected stages:

1. event contract selection
2. attribution evidence capture
3. confidence + provenance evaluation
4. outcome review packaging
5. optimization recommendations (read-model output)

High-risk boundary: unverifiable attribution and hidden confidence downgrades.

---

## 5) GTM authority layering

| Layer | Examples | Allowed effects | Forbidden effects |
|---|---|---|---|
| `declarative` | GTM capabilities, adapters, mission templates | contract persistence and validation | runtime dispatch/execute authority |
| `read_model` | GTM funnel summaries, campaign explainability projections | deterministic aggregation | mutation or dispatch |
| `governed_mutation` | approval transitions, campaign stage transitions, hold/release markers | bounded tenant-scoped state transitions | implicit multi-stage execution |
| `runtime_authoritative` | queue-backed send/publish tasks, worker-run handlers | execution under queue + lease contracts | bypassing queue, lease, or policy gate |

No GTM path may collapse declarative planning and runtime execution into a single implied action.

---

## 6) Canonical GTM mission lifecycle (contract stages)

GTM missions extend the canonical mission lifecycle with explicit outbound controls:

1. mission intake (`planned`)
2. mission plan contract
3. GTM task graph contract
4. materialization metadata
5. policy pre-screen (`outbound_policy_precheck`)
6. readiness preview (`no execution`)
7. approval checkpoint creation
8. runtime admission (only approved, policy-compliant tasks)
9. worker claim/start/run with lease authority
10. completion + evidence + outcome review

`outbound_policy_precheck` and approval checkpoint stages are mandatory for outbound-send and publish-capable mission classes.

---

## 7) Feature-flag and rollout contract

GTM runtime activation must remain feature-flagged:

- `AJENDA_GTM_CAPABILITIES_ENABLED` controls declarative GTM capability availability.
- `AJENDA_GTM_OUTBOUND_AUTOMATION_ENABLED` controls runtime binding eligibility.
- `AJENDA_GTM_HIGH_RISK_AUTOPUBLISH_ENABLED` defaults `false` and requires explicit override with governance sign-off.

Recommended rollout sequence:

1. docs + contracts (Bundle 6.1)
2. declarative catalog seeding (Bundle 6.2)
3. one low-risk runtime pilot with mandatory human gate (Bundle 6.3)
4. progressive expansion by channel and risk class

---

## 8) Security and compliance requirements

1. Tenant context validation must occur before any GTM auth resolution.
2. Contact/channel actions must remain tenant-scoped with fail-closed mismatches.
3. Policy-denied outbound actions must not enqueue runtime tasks.
4. Sensitive model-generated artifacts must preserve provenance metadata.
5. Every outbound/publish action must be attributable to actor + policy decision + mission.

---

## 9) Evidence and observability contract

Minimum evidence for GTM runtime actions:

- mission id, tenant id, capability id, adapter id
- policy decision id and policy version
- approval status and approver identity where required
- channel action request/response envelopes (sanitized)
- outcome review linkage and confidence markers

Required GTM observability categories:

- funnel progression counters
- policy deny/allow rates
- approval latency distributions
- outbound send/publish success/failure counters
- dead-letter/recovery events by GTM mission family

---

## 10) Release-gate requirements for GTM implementation bundles

For runtime-affecting GTM bundles, release promotion requires:

- baseline lint/format/non-integration tests
- targeted policy denial-path tests
- targeted runtime admission/lease/dispatch tests
- validation matrix rows proving forbidden outbound outcomes do not occur
- evidence artifact review showing policy decisions and approval checkpoints

