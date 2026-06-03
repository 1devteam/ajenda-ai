# Business Profile Implementation Contract

## 1. Purpose

This contract defines how Business Profile should be implemented after the product contract is stable.

Business Profile is durable, reusable tenant context that helps Ajenda interpret future missions. It is not a mission, not `MissionCreate`, not a Mission Brief, and not runtime authority.

This document is an implementation contract only. It does not create database tables, API routes, backend models, migrations, UI components, or runtime behavior by itself.

## 2. Non-Negotiable Rules

- Business Profile is tenant-scoped durable context.
- Business Profile never replaces `MissionCreate`.
- Mission-specific facts remain mission context unless the user approves durable promotion.
- Durable profile writes must be explicit, user-approved, auditable, and reversible by later profile updates.
- Ajenda must not silently save inferred business facts.
- Ignore / dismiss means keep going with no profile update.
- No / not now means the information stays only in the current mission.
- Business Profile may shape a Mission Brief, but neither Business Profile nor Mission Brief is runtime authority.
- Runtime execution must still pass through the governed mission/runtime bridge stages.
- Business Profile implementation must not create execution tasks, queue work, dispatch workers, mutate worker leases, promote memory, or bypass authority checks.

## 3. Data Ownership And Scope

Business Profile records belong to a tenant.

Every durable Business Profile record must include:

| Field | Requirement |
| --- | --- |
| tenant identity | required; profile data must be tenant-owned |
| profile identity | required; stable profile identifier |
| schema version | required; starts at version 1 |
| profile status | active, archived, or superseded |
| approved profile facts | durable facts approved by the user |
| provenance | how each approved fact was created or last changed |
| timestamps | created and updated timestamps |
| actor metadata | user/system identity responsible for approved writes where available |

Business Profile must not be global by default. Cross-tenant profile sharing is out of scope unless separately governed.

## 4. Approved Profile Facts

Approved profile facts are stable reusable facts about the business.

Examples:

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

Each approved fact should preserve enough provenance to answer:

- who approved it;
- when it was approved;
- whether it came from onboarding, direct profile edit, or mission-time suggestion;
- what mission or conversation produced the suggestion when applicable;
- whether the fact replaced or superseded an older value.

## 5. Profile Update Suggestions

A profile update suggestion is not a durable profile write.

A suggestion is a proposed durable fact that Ajenda believes may be reusable beyond the current mission.

Suggestions may be created from:

- onboarding answers;
- direct user profile edits;
- mission conversations;
- mission planning context;
- operator-provided corrections.

Suggestions must include:

| Field | Requirement |
| --- | --- |
| tenant identity | required |
| suggestion identity | required |
| suggested fact | required |
| suggested category | required |
| source context | mission/conversation/onboarding/profile edit context when available |
| rationale | why Ajenda thinks the fact is reusable |
| current status | pending, approved, edited, declined, dismissed, or superseded |
| created timestamp | required |
| resolved timestamp | required when no longer pending |
| resolving actor | required when approved, edited, declined, or dismissed |

## 6. User Choice Semantics

| User choice | Durable profile result | Current mission result |
| --- | --- | --- |
| Save | Ask whether to save as-is or edit first before durable write. | Current mission continues. |
| Save as-is | Store the approved fact as profile truth. | Current mission continues. |
| Edit first | Store the user-approved edited fact as profile truth. | Current mission continues with edited context if relevant. |
| No / not now | No durable profile write. | Information remains only in the current mission context. |
| Ignore / dismiss | No durable profile write. | Mission continues without engaging the suggestion. |

No, not now, ignore, and dismiss must not delete mission context already spoken by the user. They only prevent durable profile promotion.

## 7. Versioning And Supersession

Business Profile implementation must preserve history.

Minimum versioning rules:

- new approved facts create profile history;
- edited facts supersede prior approved values instead of silently overwriting without trace;
- declined or dismissed suggestions remain auditable as suggestion decisions, not as approved facts;
- profile reads should return the current active approved facts by default;
- operator/audit reads may expose prior versions and suggestion decisions where permitted.

## 8. Mission Brief Relationship

Business Profile feeds Mission Brief creation.

Mission Brief may use approved Business Profile context plus current mission intent to clarify:

- desired outcome;
- success criteria;
- constraints;
- evidence expectations;
- allowed actions/tools;
- approval requirements;
- scope, budget, region, compliance, and jurisdiction assumptions;
- missing information.

Business Profile must not write directly into runtime state. Mission Brief must not become runtime authority. Runtime execution still requires explicit mission intake, planning, graph/materialization, runtime task materialization, queue admission, dispatch readiness, and worker admission stages.

## 9. MissionCreate Relationship

`MissionCreate` remains the mission intake contract for the current mission.

Business Profile may:

- prefill mission intake fields;
- suggest defaults;
- explain likely assumptions;
- reduce repeated clarification;
- identify missing mission-critical context.

Business Profile must not:

- replace user mission intent;
- automatically create missions;
- automatically queue work;
- bypass mission validation;
- bypass runtime bridge stages;
- silently promote mission context to durable profile truth.

## 10. API Implementation Expectations

Future API work should be narrow and separately proven.

Expected future surfaces may include:

- read current Business Profile;
- update approved Business Profile facts;
- create profile update suggestions;
- approve suggestion as-is;
- approve suggestion with edits;
- decline suggestion;
- dismiss suggestion;
- read profile history/audit where permitted.

API implementation must prove:

- tenant isolation;
- permission enforcement;
- no silent writes;
- suggestion lifecycle correctness;
- audit/version history;
- no runtime side effects;
- stable read shape for Mission Brief consumers.

## 11. Storage Implementation Expectations

Future storage work must prove:

- tenant-scoped profile ownership;
- deterministic schema versioning;
- durable approved facts;
- auditable suggestion decisions;
- supersession/history semantics;
- safe JSON handling for structured profile facts;
- migration round-trip safety;
- no coupling to runtime queue/worker tables.

Storage implementation must not require all Business Profile categories to be known forever on day one. The model should allow additive, schema-versioned profile fact categories without rewriting mission intake.

## 12. Proof Requirements For First Backend PR

The first backend implementation PR must include tests proving:

- a tenant can create/read its Business Profile;
- another tenant cannot read or mutate it;
- pending suggestions do not alter approved profile truth;
- approve as-is creates an approved fact;
- edit first creates the edited approved fact, not the original suggestion text;
- no / not now leaves the suggestion unresolved or declined without durable fact promotion;
- ignore / dismiss records no approved profile fact;
- approved profile facts can be read for Mission Brief use;
- profile writes do not create missions, execution tasks, queue messages, worker leases, evidence, outcome reviews, retrieval contracts, or memory promotions.

## 13. Do Not Implement In The Same PR As Initial Storage

Do not combine initial Business Profile storage with:

- Mission Brief generation;
- UI onboarding;
- autonomous profile inference;
- memory promotion;
- retrieval/vector execution;
- runtime task creation;
- queue admission;
- worker dispatch;
- external integrations.

Initial implementation should establish durable profile truth safely before connecting it to Mission Brief or UI flows.

## 14. Completion Criteria

Business Profile implementation reaches MVP when:

- tenant-scoped profile storage exists;
- approved facts and suggestions have stable schemas;
- user choice semantics are enforced;
- audit/version history exists;
- API tests prove tenant isolation and no silent writes;
- Mission Brief consumers can read approved profile facts without mutating profile truth.

Current backend/API proof covers the storage and suggestion authority class: active-profile creation is idempotent under concurrent creation races, approved fact and suggestion JSON payloads are bounded, categories are canonicalized to avoid case/space collisions, mission-linked suggestions validate tenant ownership, profile history/supersession reads are exposed, and Business Profile mutations append audit events without creating missions, queue work, worker leases, evidence, outcome-review, retrieval, or memory-promotion state.

Remaining production-ready Business Profile work requires:

- retention/deletion policy;
- UI-supported review/edit flow;
- release-gated proof that profile context shapes Mission Brief without replacing `MissionCreate`;
- monitoring dashboards/alerts for profile update events and failures beyond append-only audit event proof.
