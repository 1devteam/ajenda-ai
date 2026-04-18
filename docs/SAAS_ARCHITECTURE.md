# Ajenda AI — SaaS Structural Enforcement Architecture

This document defines the production-grade SaaS enforcement boundaries for Ajenda AI and explains how those guarantees relate to the governed runtime and its validation model.

Ajenda is not only intended to enforce tenant, policy, and operational boundaries. It is intended to prove that those boundaries hold through explicit validation and evidence collection.

---

## 1. Purpose

Ajenda AI is a multi-tenant execution platform with SaaS governance requirements that include:

- strong tenant isolation
- subscription and quota enforcement
- compliance-aware task admission
- safe runtime execution and recovery
- auditability and release confidence

The goal of the SaaS architecture is not only to describe enforcement boundaries, but to ensure those boundaries can be evaluated and trusted in production-like runtime conditions.

---

## 2. Tenant isolation boundaries

### 2.1 Database layer

**Mechanism:** PostgreSQL Row-Level Security  
**Intent:** tenant-scoped row visibility and mutation boundaries

Tenant-aware session context is required for RLS to be meaningful. If tenant context is absent, the isolation posture should fail closed.

### 2.2 API layer

**Mechanism:** tenant-envelope and auth middleware

The API layer is responsible for:

- requiring tenant context where appropriate
- rejecting malformed tenant IDs
- rejecting suspended/deleted tenants
- rejecting cross-tenant principals
- preserving explicitly public routes where public access is intentional

### 2.3 Service and repository layer

**Mechanism:** tenant-aware business logic and repository access patterns

This acts as defense in depth above the HTTP and database boundaries.

### 2.4 Queue and worker layer

**Mechanism:** tenant-aware queue partitioning / tenant-scoped payload handling and worker checks

Workers must not execute out-of-scope tenant work.

---

## 3. Subscription and plan enforcement

### 3.1 Domain model posture

Ajenda’s SaaS model includes tenant plans, tenant usage, and route-level or operation-level quota enforcement.

### 3.2 Enforcement posture

Quota and feature enforcement should reject disallowed mutation paths before work enters authoritative runtime processing.

This keeps monetization and fairness controls aligned with runtime safety.

---

## 4. Tenant lifecycle management

Lifecycle states include:

- `ACTIVE`
- `SUSPENDED`
- `DELETED`

Lifecycle state affects:

- access
- mutation legality
- operational behavior
- tenant-scoped runtime expectations

---

## 5. Compliance and governance posture

Ajenda includes a compliance-aware queue admission path.

This means:

- unsafe or review-required work does not simply enter the queue unchecked
- policy evaluation can route work into `PENDING_REVIEW`
- governance and audit evidence are part of the system truth

This is important for enterprise saleability because governance cannot be a detached afterthought. It must participate in runtime authority.

---

## 6. Runtime authority and SaaS correctness

The SaaS architecture is inseparable from runtime authority.

Ajenda’s runtime correctness depends on:

- queue admission correctness
- lease ownership correctness
- completion/failure correctness
- recovery correctness
- tenant-safe recovery and mutation behavior

A SaaS system that enforces plans but cannot prove runtime safety is not enterprise-complete.

---

## 7. Runtime proof model

Ajenda now includes a live runtime validation layer intended to validate critical guarantees across:

- control plane
- auth and tenant envelope
- execution plane
- recovery plane
- integrity plane
- observability/compliance plane

That validation layer is the mechanism by which architecture intent becomes runtime evidence.

This matters because:

- tenant isolation must be proved, not assumed
- recovery safety must be proved, not assumed
- release decisions should be based on evidence, not architecture prose alone

---

## 8. Validation linkage for SaaS guarantees

The most important SaaS guarantees should be tied to validation rows and evidence surfaces.

Examples include:

- public-vs-protected route correctness
- missing tenant rejection
- cross-tenant rejection
- tenant-scoped queue admission
- tenant-safe recovery behavior
- no unauthorized cross-tenant runtime mutation
- governance hold behavior for pending-review tasks
- audit and evidence consistency

This linkage is what turns the architecture into an operational trust model.

---

## 9. Current architecture-to-validation principle

The right operating principle for Ajenda is:

- architecture documents define intended guarantees
- implementation defines actual behavior
- validation matrix and artifacts define trusted proof of behavior

All three matter, but release confidence should come from the last two, not the first alone.

---

## 10. SaaS-grade upgrade posture

Ajenda’s longer-term SaaS/enterprise leverage still includes areas such as:

- adaptive tenant-aware rate limiting
- stronger policy-as-code control plane
- tenant-facing operational/reliability visibility
- progressive delivery with stronger release controls

Those remain valuable, but they should build on a trusted runtime-proof foundation rather than substitute for it.

---

## 11. Current next architectural priority

The next highest-value architectural move is to strengthen the runtime validation and release-governance layer so the SaaS guarantees described in this document are tied to explicit proof surfaces.

That means:

- a more authoritative validation matrix
- clearer release semantics
- stronger coverage/maturity classification
- more deliberate proof of resilience, isolation, integrity, and forbidden outcomes

---

## 12. Summary

Ajenda’s SaaS architecture should be understood as:

- tenant enforcement boundaries
- plan and lifecycle governance
- compliance-aware runtime admission
- queue/lease/recovery safety
- and an evidence-backed runtime-proof model that validates whether those guarantees still hold

That final layer is what moves the system toward enterprise-grade operational credibility.
