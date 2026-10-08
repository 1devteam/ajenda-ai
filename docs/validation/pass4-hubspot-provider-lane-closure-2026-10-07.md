# Ajenda Pass 4 — HubSpot Provider Lane Closure

Status: implementation corrected after PR review; repository validation and the credentialed live replay proof must be rerun on the current PR head before merge.

## Baseline and scope

- Current-main baseline: `a5fdcb81fda8c1e9cb74190b16ddfe896f9c9250`
- Provider lane: HubSpot only
- Pass 3 work was not cherry-picked or revived.
- Deferred: Gmail/email, Salesforce, Calendar, SaaS/onboarding, presentation, and general production completion.

## Capability matrix

| Requirement | Canonical owner | Implementation/proof | Result |
|---|---|---|---|
| Customer credential registration | `ProviderCredentialManagementService`, provider credential API | Public signup/verification/bootstrap promotion and `POST /v1/account/provider-credentials` | Proven |
| Tenant-scoped credential reference | runtime credential repository/authority | Mission/task graph stores `credential_id`, provider, type, and schema only; secret resolves at runtime | Proven |
| Capability authority | ability catalog, `validate_capability_action_authority`, bridge adapter | Real declarations; no monkeypatch; external write adapter classification | Proven |
| HubSpot composition | intent interpreter, job catalog, action inputs | Natural HubSpot instruction selects `sales.research`, contact observation, qualification, enrichment, and `gtm.crm_upsert`; no web search | Proven |
| Runtime credential resolution | `CredentialRuntimeAuthority` and runtime repository | Worker resolves tenant/provider/action credential at execution time | Proven by worker proof and authority tests |
| HubSpot adapter/ingress | `services/hubspot_crm_adapter/*` | TLS ingress and governed egress reach the real HubSpot API | Proven |
| Real provider read | `StandardCrmClient.search`, `sales.research` | Real company and contact records, provider identity and status retained | Proven |
| Governed provider write | `gtm.crm_upsert`, `ExecutionCoordinator` | Pending review, machine denial, owner approval, payload-bound grant, queue, worker | Proven |
| Effect verification | `StandardCrmClient.readback`, adapter read endpoint | Provider ID plus provider-returned requested properties are compared against GET read-back; mismatches fail closed | Implemented; regression covered |
| Evidence and deliverable | runtime evidence and deliverable projection | Typed artifacts, evidence lineage, customer-readable deliverable | Proven |
| Reconciliation | queue/runtime evidence and acceptance services | Acceptance met, queue admitted, no pending review, runtime reconciliation aligned | Proven |
| Idempotency | mission/task materialization, `gtm.crm_upsert`, adapter identity lookup | Stable launch/write identity is propagated; the live proof now replays the same completed mission and requires zero new tasks/queue admissions plus the same verified HubSpot record ID | Implemented; live replay rerun required |
| Retry/recovery | queue, lease, dispatcher, recovery services | Existing recovery/unit/integration gates selected; no second recovery architecture added | Existing platform proof; provider-specific fault injection remains deferred |
| Tenant isolation | API/service/repository boundaries | Second tenant cannot approve or read the first tenant's mission evidence | Proven in public proof |

## G.R.A.F.T. pre-change analysis

Generated from current main before production edits with `build_dependency_graph.py`:

- 1,632 graph nodes and 4,706 edges.
- Predicted surfaces: mission composition, action inputs, CRM client, HubSpot adapter/ingress, worker/evidence/reconciliation, review queue, credential authority, tests, proof, and validation documentation.
- Initial impact analysis: 10 changed candidate nodes, 152 affected semantic nodes, 165 downstream nodes, 350 upstream nodes, 192 impacted tests, 9 invariants, and 2 risk domains.
- GRAFT selected the worker spine, tenant isolation, side-effect approval, retry/readmission, runtime-secret, governed-egress, state-ownership, and action-contract proof bundles.
- The graph explicitly predicted that queue-admission changes should wait for a real worker contradiction.

## Implementation changes and first divergences

Observed runtime divergences were repaired at their canonical owners:

1. Explicit “one” was defaulted to three by intent parsing. The quantity parser now preserves explicit word quantities.
2. HubSpot research completed without its declared `prospect_candidates` artifact. The producer now emits a normalized typed artifact from real provider evidence.
3. HubSpot qualification had real identity/contactability but a generic score below the provider-lane acceptance threshold. Provider-verified identity now contributes to the business-fit dimension; the explicit HubSpot lane uses the existing observed-contact threshold while leaving unknown urgency/automation unclaimed.
4. Bridge authority read credential references from `input_contract`, not only a top-level node field. The bridge now resolves both canonical representations and provisions `external_write` authority.
5. The adapter received Ajenda qualification/lineage fields as HubSpot properties and HubSpot rejected the payload. The adapter now projects only supported provider properties; Ajenda evidence remains in typed artifacts.
6. `gtm.crm_upsert` returned `external_crm` while its registered action provider is `ajenda_brain`. The action result now preserves the registry provider contract and carries external provider identity in its output/evidence payload.
7. A successful human approval could leave a transient review-hold reconciliation receipt. `ExecutionCoordinator` now reconciles the exact reviewed task after successful enqueue and clears only that task's review blocker.

No authority was weakened, no machine approval permission was added, and no admin impersonation was used.

## Live worker proof

Proof entry point: `deploy/scripts/pass4-hubspot-provider-proof.py`

Final successful proof:

- Tenant: `93f93f4d-a562-410a-8053-400150fbd3eb`
- Mission: `ad9c1613-235d-416c-8980-ede885edaa68`
- Governed write task: `09c3c536-c752-4995-9304-788267a2ea32`
- Mission status: `completed`
- Acceptance: `met`
- Queue admission: `admitted`
- Pending review IDs after approval: `[]`
- Runtime reconciliation: `status=aligned`, `reason=reviewed_task_admitted`
- Provider result: `upserted_real`
- Provider record: HubSpot contact `508583344859`
- Read-back: verified, provider source `hubspot`, contact email and company returned by GET

The proof used two identities. The `tenant_operator` machine key was denied approval with 403. The password-authenticated `tenant_owner` session had `outcome_review:manage` and approved only after dependency readiness. The proof also checked that a second tenant could not approve the review task or read mission runtime evidence.

The credential was registered through the public provider-credential API. Only the credential reference appeared in composition/runtime state; the proof failed if the plaintext token appeared in registration response, composition, launch, runtime evidence, or deliverable.

## Security and recovery notes

- Trusted destination enforcement remains in `NetworkEgressAuthority`.
- Missing/invalid/revoked credential behavior remains fail-closed at runtime credential authority.
- External writes remain independently approved and payload-bound.
- Existing queue/lease/recovery infrastructure and its tests remain the recovery owner.
- HubSpot CRM v3 does not provide a native `Idempotency-Key` contract for this adapter. Ajenda propagates a stable idempotency key and the adapter performs identity-based upsert (`email` for contacts) before create, preventing an unintended duplicate on replay when the same identity is used. This is distinct from claiming provider-native idempotency.
- Provider fault injection for timeout/5xx and mutation-success/evidence-failure compensation is not fabricated by the live proof and remains a follow-up to the generic recovery contract.

## Validation

Focused tests passed during implementation:

- HubSpot adapter, CRM client/read-back, GTM pipeline artifacts, sales qualification, mission composition, bridge authority, coordinator, and mission repository tests.
- Ruff format/check passed for each changed surface.

The final repository-wide validation commands and their exact results are recorded below before commit/PR handoff.

## G.R.A.F.T. post-run reconciliation

The post-run graph was regenerated against the final changed-file set:

- 1,632 nodes and 4,706 edges.
- 21 changed-file inputs at the reviewed PR head, 67 changed graph nodes, 152 affected semantic nodes, 226 downstream dependencies, 336 upstream consumers, 197 impacted tests, 9 invariants, and 3 risk domains.
- The only unmapped files were the intentional proof entry point and this closure document; no production, runtime, authority, or provider file was unmapped.
- The first live divergences (quantity parsing, declared artifact production, bridge credential location, provider payload projection, action provider contract, and review-hold reconciliation) were all represented by the predicted composition/provider/runtime risk domains and repaired at their canonical owners.
- GRAFT selection was sufficient to identify the final production repair surfaces; the live proof supplied the missing runtime evidence needed to justify the bridge and post-approval reconciliation repairs.

## Previously recorded validation results

- `ruff check backend/ tests/ scripts/validation/`: passed.
- `ruff format --check backend/ tests/ scripts/validation/`: passed; 1,025 files formatted.
- `mypy backend/`: passed; 439 source files.
- Contract drift, runtime-authority inventory, migration/seed, ability-rollout, and GRAFT reconciliation checks: passed.
- Before the review corrections, `python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration"` recorded 3,181 passed, 1 deselected. The current PR head adds a read-back mismatch regression and must be rerun before merge.
- The targeted HubSpot credential integration test was updated for read-back and skipped in this shell because the testcontainers Docker daemon was unavailable; the dedicated real Docker worker proof above passed.

## Deferred scope

- Gmail/email, Salesforce, Calendar, onboarding/SaaS, UI, and production-completion work.
- Native provider-side idempotency guarantees, because HubSpot CRM v3 exposes no native idempotency endpoint in this lane.
- Provider fault-injection campaigns that require a controlled HubSpot timeout/5xx or downstream persistence failure after a successful remote mutation.

Review correction: `330833c653abf2817fdce95d564037794e6b18f4` was an intermediate local validation SHA and was not the GitHub PR head. The reviewed PR head was `e4dffa72205e6e49283a78cc46d5c4010e135070`; subsequent corrective commits are authoritative from the PR branch itself, so this document intentionally does not embed a self-referential "final SHA".
