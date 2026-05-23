# AJENDA-AI Project Specification (Canonical)

**Version:** 0.1.0  
**Status:** Active  
**Effective date:** May 23, 2026  
**Owner:** Obex Blackvault  
**Repository:** `github.com/1devteam/ajenda-ai`

---

## 1) Purpose and mission

AJENDA-AI is a governed, multi-tenant mission-execution platform that converts business outcomes into structured, policy-constrained, queue-authoritative runtime operations with verifiable evidence.

Primary mission:

- safely execute tenant-scoped machine work
- preserve tenant isolation across every layer
- enforce fail-closed auth and policy boundaries
- maintain queue + lease runtime authority
- provide bounded recovery and auditable outcomes
- promote releases from runtime proof, not assumption

---

## 2) Scope and non-goals

### In scope

- mission intake, mission planning, task-graph contract layers
- governed mission-to-runtime bridge stages
- queue-backed execution + worker lease lifecycle
- policy/compliance gates and pending-review pathways
- evidence, outcome review, and retrieval governance contracts
- observability metrics + audit/governance events
- runtime validation matrix and release-gating scenarios

### Out of scope (current)

- unconstrained autonomous execution that bypasses queue/lease authority
- implicit runtime dispatch from declarative contracts
- autonomous outcome scoring that mutates runtime state without explicit authority
- any cross-tenant mutation pathways

---

## 3) Non-negotiable invariants

1. **Tenant isolation is mandatory** at HTTP, service, repository, and DB layers.  
2. **Runtime queue authority is mandatory** for admitted work.  
3. **Worker lease ownership is mandatory** for claim/start/run authority.  
4. **Recovery must be bounded and evidence-backed.**  
5. **Auth and policy are fail-closed.**  
6. **Declarative contracts do not imply execution authority.**  
7. **Release confidence comes from runtime evidence and gates.**

---

## 4) Authority model by layer

### A. Declarative contract layer

Examples:

- capability registry
- capability adapters
- mission plans
- task graph metadata
- evidence/outcome/retrieval contract records

Authority class: `declarative`  
Allowed effects: persistence + validation of declared contract shape  
Forbidden effects: dispatch/execute runtime work unless a separate explicit authority contract allows it

### B. Read-model layer

Examples:

- mission lifecycle read model
- readiness/readiness-preview style read surfaces
- explainability and summary projections

Authority class: `read_model`  
Allowed effects: deterministic aggregation only  
Forbidden effects: mutation and dispatch

### C. Governed mutation layer

Examples:

- mission bridge mutations (materialization/admission/claim/start where explicitly defined)
- policy-governed state transitions

Authority class: `governed_mutation`  
Allowed effects: narrow, explicit, tenant-scoped state changes with validation  
Forbidden effects: collapsing multiple authority stages into implicit all-in-one execution

### D. Runtime authoritative layer

Examples:

- queue-backed task execution
- worker claim/start/run with lease ownership
- completion/failure/dead-letter/recovery semantics

Authority class: `runtime_authoritative`  
Allowed effects: execution and runtime state transitions under queue + lease authority  
Forbidden effects: synthetic execution bypassing authoritative runtime contracts

---

## 5) Mission contract classes

Mission lifecycle contracts are staged and explicit:

1. mission intake (`planned` mission creation + intake envelope)
2. mission plan (durable plan contract)
3. task graph (normalized graph contract)
4. planner-to-graph materialization metadata
5. runtime admission metadata
6. readiness/preview checks (read-only)
7. runtime task materialization (planned tasks only where defined)
8. worker claim admission
9. worker start admission
10. worker run admission (runtime bridge into dispatcher path)

All stages must remain bounded; no implicit skipping of queue, lease, dispatcher, or recovery authority.

---

## 6) Schema compatibility policy

1. Additive-first changes; avoid destructive changes in feature PRs.
2. Contract envelopes must use schema versioning.
3. Unknown future versions must fail closed (no guesswork compatibility).
4. No silent repurposing of existing keys.
5. Transition strategy should allow dual-read when needed.
6. Schema-impacting PRs require migration contract tests and rollback notes.

---

## 7) Security, auth, and policy requirements

- tenant context must be validated before auth resolution where required
- cross-tenant principal/request mismatch must fail closed
- API-key flows must remain tenant-scoped
- policy/compliance checks must be able to block unsafe admission
- sensitive failures (especially readiness/security surfaces) must be sanitized
- webhook/signing-secret handling must maintain protected storage posture

---

## 8) GTM self-selling mission scope (future-bound but planned)

AJENDA-AI is intended to support governed self-selling workflows, including:

- lead discovery and qualification missions
- outreach and follow-up sequencing missions
- social and blog content pipeline missions
- attribution and conversion evidence missions

### GTM non-goals (until explicitly implemented and gated)

- autonomous high-risk outbound publishing without policy/human gate
- direct execution authority from capability declaration records
- non-auditable channel actions

GTM runtime activation must be feature-flagged and policy-gated.

---

## 9) Observability and evidence requirements

Required observability posture:

- Prometheus metrics surface
- audit and governance event records
- runtime validation artifacts
- dead-letter and recovery visibility
- mission- and tenant-scoped evidence traceability

All critical control-plane and runtime mutations must leave reviewable evidence.

---

## 10) Release-gate policy

Minimum baseline gates for change PRs:

- `ruff check .`
- `ruff format --check .`
- `python -m pytest -m "not integration"`

Additional required gates when runtime semantics are touched:

- targeted contract tests
- targeted integration tests
- validation matrix scenario updates where behavior contracts changed

Promotion policy:

- no promotion when required proof surfaces are missing or contradictory
- runtime truth overrides doc intent in release decisions

---

## 11) Documentation governance

Canonical source-of-truth docs:

1. `PROJECT_SPEC.md` (this file)
2. `README.md`
3. `docs/product/mission-based-ai-core.md`
4. `docs/SAAS_ARCHITECTURE.md`
5. `docs/validation/live-runtime-matrix.md`
6. `docs/validation/live-runtime-proof-release-gate.md`
7. `docs/deployment/production-env-contract.md`

If documents conflict, precedence order is:

1. implementation + tests + runtime proof artifacts
2. `PROJECT_SPEC.md`
3. README and architecture docs

---

## 12) 90-day execution priorities (from remediation plan)

1. Bundle 0: canonical spec + ADR index + docs freshness policy
2. Bundle 1: authority ledger + drift sentinel + operator cues
3. Bundle 2: readiness semantics hardening
4. Bundle 3: lifecycle governance explicitness
5. Bundle 4: explainability + reliability read models
6. Bundle 5: economic observability scaffolding
7. Bundle 6: GTM capability contracts and controlled pilot

---

## 13) Change control protocol

Any change that affects authority class, tenant isolation, runtime state transitions, policy behavior, or release gating must include:

- explicit design note (what changed, why, risk class)
- backward compatibility note
- test evidence and validation impact summary
- rollback strategy

No exceptions for “small” changes in these domains.
