# Mission Brief Read Model Contract

## 1. Purpose

Mission Brief is the read-only contract that turns current mission-specific intent into a structured, operator-reviewable draft using approved Business Profile context and explicit request context.

It is not `MissionCreate`, not a `Mission`, not a `MissionPlan`, not a task graph, and not runtime authority.

## 2. Authority Boundary

Mission Brief authority class is `read_model`.

Allowed behavior:

- read tenant-approved Business Profile facts;
- read the current request's mission-specific intent;
- read explicit request context supplied for the draft;
- deterministically aggregate those inputs into a bounded draft/readiness response;
- identify missing mission-critical information;
- suggest `MissionCreate` field prefill/defaults with provenance.

Forbidden behavior:

- create a `Mission`;
- create or update `MissionPlan` records;
- create task graph metadata;
- create `ExecutionTask` records;
- enqueue queue messages;
- create or mutate worker leases;
- create evidence, outcome-review, retrieval, or memory records;
- mutate Business Profile truth or silently promote current mission context into durable profile facts;
- bypass mission validation, planning, runtime task materialization, queue admission, dispatch readiness, or worker admission.

## 3. Inputs

`POST /v1/mission-briefs/draft` consumes:

| Input | Requirement |
| --- | --- |
| approved Business Profile facts | read from the tenant's active Business Profile when present |
| current mission-specific intent | request body fields that mirror the mission intake shape but remain optional |
| explicit request context | bounded JSON context for the current draft request |

Current mission-specific intent always wins over Business Profile defaults. If both exist and conflict, the response must preserve the user's current mission value and report the conflict.

## 4. Outputs

The Mission Brief response includes:

| Output | Purpose |
| --- | --- |
| structured brief | outcome-first interpretation of the current request |
| missing information checklist | blockers and warnings for absent mission-critical context |
| suggested MissionCreate fields | a draft prefill/default payload, not a created mission |
| provenance | field-level source details from mission input, Business Profile, or system defaults |
| conflicts | cases where current mission input overrides profile defaults |
| readiness | whether the draft has enough required information for explicit MissionCreate |
| authority flags | proof that the response is read-only and not runtime authoritative |

## 5. Missing Information Rules

Mission Brief must not fabricate required mission intent.

At minimum, the draft must report blockers when current mission intent does not provide:

- objective;
- success criteria.

The draft may report warnings for recommended planning context such as missing allowed actions or allowed tools.

## 6. Business Profile Use

Business Profile may provide reusable defaults such as:

- allowed actions;
- allowed tools;
- approval requirements;
- budget or scope limits;
- compliance category;
- jurisdiction;
- reusable business context such as business name, service area, offerings, target customers, team roles, and evidence expectations.

Business Profile must not replace the user's current mission-specific objective or success criteria.

## 7. Proof Requirements

Current implementation proof:

- `backend/api/routes/mission_brief.py`;
- `backend/services/mission_brief_read_model.py`;
- `tests/unit/api/test_mission_brief_route.py`;
- `docs/contracts/authority-ledger.v1.yaml`.

Required proof behavior:

- current mission input wins over conflicting Business Profile defaults;
- missing required intent is reported instead of fabricated;
- suggested MissionCreate fields include field-level provenance;
- authority flags prove no mission/runtime authority;
- route tests prove no mission, plan, task, queue, worker lease, evidence, outcome, retrieval, or memory side effects.
