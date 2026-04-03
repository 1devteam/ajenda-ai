# Ajenda AI — Compliance & Security Architecture

## The Problem
Ajenda AI operates governed workflows. However, without a deterministic classification engine, the platform cannot know if a workflow falls under regulated categories (e.g., employment, credit, consumer-facing AI). This creates a compliance risk under the EU AI Act, Colorado SB24-205, NYC LL144, CAN-SPAM, and TCPA.

## The Solution

This architecture introduces a first-class compliance layer that intercepts, classifies, and enforces policy on all governed workflows.

### 1. Workflow Classification Engine
Every `Mission` and `ExecutionTask` must be classified before execution.
- **Categories:** `operational`, `consumer_interaction`, `marketing`, `employment`, `financial`, `healthcare`, `public_content`.
- **Enforcement:** The `PolicyGuardian` blocks execution if a regulated category lacks the required compliance contracts (e.g., disclosure, human review).

### 2. Jurisdiction-Aware Policy
Policies are evaluated based on the tenant's operating jurisdiction (e.g., `EU`, `US-CO`, `US-NY`).
- **Example:** A `consumer_interaction` task in `US-CO` requires explicit disclosure of AI interaction (SB24-205).
- **Example:** An `employment` task in `US-NY` requires an active bias audit reference (NYC LL144).

### 3. Consumer Disclosure & Content Labeling
- Regulated tasks must attach a `DisclosureContract` to their payload.
- Content generated for public or consumer consumption must carry an AI provenance label.

### 4. Human Review & Appeal Paths
- Tasks making "consequential decisions" (e.g., hiring, credit) must implement an `AppealContract`.
- The `RuntimeGovernor` routes appealed tasks to a dedicated `human_review` queue.

### 5. Immutable Governance Evidence Store
- The existing `audit_events` and `governance_events` are hardened.
- All policy decisions, disclosures, and human reviews are written to the `governance_events` table as append-only, cryptographically verifiable records.

## Implementation Plan
1. **Domain Models:** Add `ComplianceClassification`, `DisclosureContract`, `AppealContract` to `enums.py` and models.
2. **Migrations:** Add `compliance_category`, `jurisdiction`, and `requires_human_review` to `missions` and `execution_tasks`.
3. **Services:** Upgrade `PolicyGuardian` to enforce classification rules.
4. **Middleware:** Add `ComplianceContextMiddleware` to inject jurisdiction context.
5. **Testing:** Add compliance test suites for EU AI Act, Colorado SB24-205, etc.
