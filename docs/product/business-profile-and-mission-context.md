# Business Profile And Mission Context

## Purpose

Business Profile is reusable tenant context that helps Ajenda turn natural mission requests into structured, executable Mission Briefs without making the user layer rigid or form-driven.

This contract is additive. It does not replace mission intake, `MissionCreate`, mission planning, task graphs, runtime materialization, queue admission, worker admission, or queue/worker execution.

Core rule:

> The user speaks mission. The Business Profile supplies reusable context. Ajenda builds structure. Runtime executes safely.

## Product Position

Ajenda remains mission-driven at the user layer. Users should be able to describe outcomes in business language without learning internal runtime concepts such as queues, leases, task graph materialization, dispatch readiness, worker claims, or recovery.

Business Profile exists so users do not have to restate stable business context every time they create a mission. It should reduce ambiguity while preserving natural mission entry.

Business Profile is not a mission. A mission is still the specific outcome requested now. Business Profile is the reusable operating context that helps shape that mission.

## Relationship To Existing Mission Intake

Business Profile feeds mission intake. It does not supersede mission intake.

Existing mission intake remains responsible for the specific mission request and its structured mission fields, including objective, success criteria, constraints, priority, approval expectations, budget and scope limits, allowed actions/tools, compliance category, and jurisdiction.

Business Profile may help prefill, suggest, or clarify mission fields, but every mission still needs its own explicit Mission Brief and runtime contract path before execution.


## Mission Brief Read-Model API Contract

`POST /v1/mission-brief/draft` is the backend read surface for Bundle 2 Mission Brief readiness. It deterministically combines approved active Business Profile facts, current mission-specific intent, and explicit request context into a bounded draft response.

The response includes:

- a structured Mission Brief summary;
- a missing-information checklist for required or recommended mission intake data;
- a deterministic readiness summary that separates required `MissionCreate` blockers from non-blocking recommendations;
- suggested `MissionCreate` prefill/default values;
- field-level provenance showing whether values came from current intent, Business Profile, request context, or system defaults;
- conflict records where current intent differs from reusable profile defaults;
- authority flags proving the result is a read model only.

Current mission intent wins over Business Profile defaults. Conflicts are surfaced for review; they are not resolved by mutating profile truth or creating runtime work. Missing required `MissionCreate` fields are reported instead of fabricated. The readiness state is `blocked` only when required information is missing; recommended clarifications remain visible without preventing explicit MissionCreate review. Mission Brief list fields and generated `MissionCreate` prefill lists must stay inside bounded item-count and per-item length limits before they are returned; overflow or invalid values are omitted from generated read-model/pre-fill surfaces and, where applicable, returned as missing/clarification information for review.

Mission Brief draft generation must not create `Mission`, `MissionPlan`, task graph metadata, `ExecutionTask`, queue messages, worker leases, evidence, outcome-review, retrieval, durable Business Profile truth, or memory-promotion records. Runtime execution still starts only after explicit mission intake and the governed mission/runtime bridge stages.

## Business Profile Scope

A Business Profile should capture stable tenant/business facts, such as:

- business name;
- business type or industry;
- service areas or operating regions;
- products, services, or offerings;
- target customers or customer segments;
- team roles and worker responsibilities;
- allowed actions and allowed tools;
- approval rules and escalation expectations;
- evidence expectations for useful outputs;
- default scope, budget, compliance, or jurisdiction assumptions.

The profile should stay lightweight at onboarding. It should grow progressively as the user works with Ajenda.

## Simple Onboarding

A simple onboarding form may collect the minimum reusable context needed to make early missions clearer.

The onboarding form must not become a giant required questionnaire. It should gather enough context to help Ajenda understand the business, then allow the profile to improve over time through user-approved updates.

Recommended initial onboarding fields:

- business name;
- type of business;
- primary services or products;
- service area or market;
- target customers;
- team or worker roles;
- actions Ajenda may prepare, recommend, or perform;
- actions requiring approval;
- evidence expectations for results.

## Profile Update Suggestions

Ajenda may identify possible durable business facts during mission conversations. When that happens, Ajenda should ask the user before saving the fact to the Business Profile.

Ajenda must not silently rewrite durable business profile truth.

Example durable facts:

- service area changed;
- business no longer serves a customer segment;
- a new product or service is offered;
- a team member has a stable role;
- outreach requires approval;
- pricing must never be quoted automatically;
- every lead requires source evidence and a qualification reason.

## User Choice Flow

When Ajenda detects a possible profile update, it should present a lightweight suggestion rather than interrupting the mission with a heavy form.

Every persisted suggestion carries a server-generated proposal binding. Approval records a second
application binding containing the proposal digest, tenant/profile/category identity, the exact
approved fact digest, the prior profile state digests, and the approval decision. If the proposal
content changes after review, application fails closed. These bindings provide provenance and
tamper evidence; they do not grant runtime authority or bypass the normal profile permission gate.

Choice behavior:

| User choice | System action |
| --- | --- |
| Save | Ask whether to save as-is or edit first. |
| Save as-is | Store the approved fact in the Business Profile. |
| Edit first | Let the user revise the proposed fact, then store the approved version. |
| No / not now | Keep the information only in the current mission. |
| Ignore / dismiss | Keep going; no profile update. |

No, not now, ignore, and dismiss do not erase the information from the current mission. The information remains available only where it was already spoken: inside the current mission or conversation context. It becomes reusable future profile context only after user approval.

## Mission Brief

A Mission Brief is the structured interpretation of the current mission request using the approved Business Profile plus the user’s current mission-specific intent.

The Mission Brief should remain outcome-first. It should not expose runtime internals to non-technical users.

The Mission Brief should clarify:

- what outcome the user wants;
- how success will be measured;
- what evidence should prove completion;
- what constraints apply;
- what actions/tools are allowed;
- what requires approval;
- what scope, budget, market, or compliance assumptions apply;
- what information is missing before planning or runtime execution.

## Mission-Driven UX Rule

Business Profile must not force every user into a rigid predefined mission type.

Mission types may be suggested as shortcuts or clarifying language, but they must not become cages that override the user’s outcome. The product should ask only for missing mission-critical details.

Good behavior:

- User gives a natural mission.
- Ajenda uses Business Profile to draft a Mission Brief.
- Ajenda asks only for missing critical details.
- Ajenda suggests profile updates only when reusable durable facts appear.
- The user controls what becomes future profile truth.

Bad behavior:

- forcing every mission into a long form;
- requiring fixed mission templates before a user can state an outcome;
- silently saving inferred business facts;
- making users understand queues, workers, leases, runtime materialization, or recovery;
- treating one mission’s temporary context as durable profile truth without approval.

## Implementation Boundary

This document defines product behavior and future contract direction only. It does not introduce database tables, API routes, backend models, migrations, UI components, or runtime behavior by itself.

Future implementation should proceed in focused PRs:

1. Business Profile implementation contract. See `docs/product/business-profile-implementation-contract.md`.
2. Business Profile domain and storage contract.
3. Profile update proposal contract.
4. API routes for reading/updating approved profile context.
5. Mission Brief generation/readiness contract.
6. UI onboarding and profile update suggestion flow.

Each implementation PR must preserve the rule that Business Profile is additive context above mission intake, not a replacement for mission intake or runtime governance.
