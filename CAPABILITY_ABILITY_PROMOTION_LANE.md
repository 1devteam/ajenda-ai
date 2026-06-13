Repository: 1devteam/ajenda-ai
Base branch: main

Title:
Complete Capability and Ability Runtime Promotion lane

Mission:
Bring the Capability / Adapter / Ability Runtime Promotion lane to completion in one PR laboratory.

This is not a small patch PR. This is one lane-completion pass. The goal is to complete all lane-owned missing work for Ajenda’s capability, adapter, and ability promotion system now that the Tool Runtime Authority lane and Network Egress Authority lane have been completed.

Desired outcome:
After this pass, Ajenda should have a complete governed promotion lane that decides which abilities are available, which capabilities and adapters may support them, which tenants may use them, what side-effect authority is required, and what proof is required before runtime execution is allowed.

The completed lane must make this true:

AbilityManifest / Capability / Adapter declaration
→ rollout validation
→ tenant-visible capability/adapter eligibility
→ side-effect classification compatibility
→ approval/idempotency/readback/evidence requirements
→ concrete action authority
→ ToolRuntimeAuthority
→ ActionRegistry
→ tool action execution

Capabilities, adapters, and abilities must become a coherent promotion and eligibility authority layer. They must not become a second runtime engine.

Complete state:
The lane is complete when the repo has one coherent capability/ability promotion model proving:

1. Ability manifests define rollout/proof expectations for every canonical registered action.
2. Every registered canonical action has exactly one valid manifest or an explicitly documented exception.
3. Ability manifests cannot execute runtime work by themselves.
4. Capability records cannot execute runtime work by themselves.
5. Adapter records cannot execute runtime work by themselves.
6. Capability/adapter declarations can only authorize concrete actions through ToolRuntimeAuthority.
7. Side-effect classifications remain exact for external read/write/send/publish classes.
8. Broad legacy external_side_effect cannot authorize concrete external runtime classes.
9. Tenant-visible capability/adapter scope is enforced before side-effecting runtime actions.
10. Disabled capabilities/adapters cannot authorize runtime action execution.
11. Capability/adapter compatibility is validated centrally and consistently.
12. Ability rollout rules enforce approval, idempotency, evidence, and readback/deferred-readback expectations.
13. High-risk or external side-effect abilities cannot silently become enabled-by-default runtime powers.
14. Promotion state is explicit enough to distinguish declarative existence from runtime eligibility.
15. Runtime denial reasons are deterministic and testable.
16. Docs, authority ledger, and validation scripts describe the completed lane without claiming CRM/GTM SaaS provider activation, OAuth, credential refresh, or durable third-party provider clients.

Read first:
Read these files completely before modifying anything:

* PROJECT_SPEC.md
* docs/product/mission-runtime-architecture-map.md
* docs/product/ability-rollout-contract.md
* docs/contracts/authority-ledger.v1.yaml
* docs/validation/live-runtime-matrix.md
* backend/services/tools/runtime_authority.py
* backend/services/tools/action_registry.py
* backend/services/tools/capability_validation.py
* backend/services/tools/schemas.py
* backend/services/abilities/manifest.py
* backend/services/abilities/catalog.py
* backend/services/abilities/rollout_validation.py
* backend/services/capability_adapter_compatibility.py
* backend/api/routes/capability_adapter.py
* backend/api/routes/capability.py if present
* scripts/validation/ability_rollout_contract_check.py
* tests/unit/tools/test_capability_action_validation.py
* tests/unit/tools/test_action_registry.py
* tests/unit/services/test_capability_adapter_compatibility.py
* tests/unit/api/test_capability_adapter_route.py
* tests/unit/db/test_gtm_catalog_seed_migration_contract.py
* tests/unit/architecture/test_authority_ledger_contract.py
* tests/unit/validation/test_contract_drift_check.py

Also search the repo before deciding implementation shape:

* AbilityManifest
* ability manifest
* ability_rollout_contract_check
* Capability
* CapabilityAdapter
* capability_adapter
* adapter classification
* side_effect_classification
* external_side_effect
* external_read
* external_write
* external_send
* external_publish
* approval_required
* idempotency_required
* readback
* evidence
* enabled_by_default
* validate_capability_action_authority
* capability_action_runtime_contract
* concrete action authority
* tenant visibility

Boundaries:
Do not:

* Create a second runtime engine.
* Move runtime execution into capability routes, adapter routes, ability catalog, or manifest validation.
* Bypass ToolRuntimeAuthority.
* Bypass ActionRegistry.
* Bypass NetworkEgressAuthority for outbound network work.
* Change queue, worker lease, dispatcher, or WorkerRuntimeService ownership.
* Activate real CRM/GTM SaaS providers.
* Add OAuth, credential refresh, secret storage, or third-party provider SDK calls.
* Treat manifest existence as runtime permission.
* Treat capability existence as runtime permission.
* Treat adapter existence as runtime permission.
* Collapse external read/write/send/publish authority into external_side_effect.
* Weaken the exact external side-effect classification work already merged.
* Add docs claiming runtime promotion behavior without tests proving it.

Pitfalls:
Watch for these failure modes:

* Calling the lane complete while manifests remain only loose documentation.
* Letting enabled_by_default silently create runtime authority.
* Treating tenant-visible records as execution authority without side-effect approval.
* Letting broad tool.invoke support authorize concrete side-effecting actions.
* Reintroducing external_side_effect as a universal external permission.
* Creating a provider activation path before credential/provider security is ready.
* Adding capability/adapter route behavior that mutates runtime state directly.
* Writing migration or seed changes that break already-applied database upgrade paths.
* Adding validation checks that only inspect docs but do not prove runtime denial paths.
* Overclaiming CRM/GTM completion.

Implementation expectation:
Codex should decide the exact implementation after reading the repo, but the likely completion shape is:

* strengthen the ability manifest model and validation so manifests are canonical rollout/proof contracts for registered actions;
* strengthen runtime capability/adapter validation so concrete action authority, tenant scope, enabled/disabled state, side-effect class, approval requirement, idempotency requirement, and evidence/readback expectations are consistently enforced;
* ensure route/schema/API contract surfaces for adapters support exact external classifications without making declarations executable;
* add deterministic denial reasons where missing;
* add or update validation scripts so action registry, ability manifests, capability/adapter compatibility, and authority ledger cannot drift;
* update docs and authority ledger only where implementation truth changes.

Do not produce an audit-only PR. Implement all lane-owned missing work.

Proof requirements:
Add or update tests proving:

1. Every canonical registered action has a valid ability manifest or documented exception.
2. Ability manifests do not execute work.
3. Capability records do not execute work.
4. Adapter records do not execute work.
5. Side-effecting runtime actions fail without concrete capability/adapter authority.
6. Side-effect authorization alone does not bypass capability/adapter authority.
7. Disabled capabilities are rejected.
8. Disabled adapters are rejected.
9. Tenant scope is enforced for capability/adapter authority.
10. Broad tool.invoke authority is not enough for concrete side-effecting actions.
11. external_side_effect does not authorize external_read, external_write, external_send, or external_publish.
12. exact external classifications authorize only their matching concrete side-effect class.
13. approval-required abilities cannot silently become enabled runtime powers.
14. idempotency-required side-effect abilities have a validated idempotency contract or fail validation.
15. evidence-required abilities have validated evidence expectations.
16. write/send/publish abilities require readback or documented deferred-readback reason.
17. high/critical-risk abilities cannot be enabled by default unless the contract explicitly allows it.
18. runtime denial reasons are deterministic and test-covered.
19. migration/seed contracts remain upgrade-safe if any catalog seed or enum changes are needed.
20. docs/authority ledger/validation scripts match implementation.

Suggested test commands:
Search first; do not assume a test file exists.

Run targeted tests:

PYTHONPATH=. pytest -q 
tests/unit/tools/test_capability_action_validation.py 
tests/unit/tools/test_action_registry.py 
tests/unit/services/test_capability_adapter_compatibility.py 
tests/unit/api/test_capability_adapter_route.py 
tests/unit/db/test_gtm_catalog_seed_migration_contract.py 
tests/unit/architecture/test_authority_ledger_contract.py 
tests/unit/validation/test_contract_drift_check.py 
-ra

Also run any ability-specific tests that exist after repo search.

Run validation:

PYTHONPATH=. ruff check backend/ tests/ docs/ scripts/validation/ alembic/versions/
PYTHONPATH=. ruff format --check backend/ tests/ docs/ scripts/validation/ alembic/versions/
PYTHONPATH=. mypy backend/
PYTHONPATH=. python scripts/validation/contract_drift_check.py
PYTHONPATH=. python scripts/validation/ability_rollout_contract_check.py
PYTHONPATH=. python scripts/validation/migration_seed_contract_check.py

If runtime semantics are touched, also run:

PYTHONPATH=. python -m pytest tests/unit/ tests/contract/ tests/deployment/ -m "not integration" -ra

Documentation/contract updates:
Update only what is true after implementation.

Expected docs/contract surfaces:

* docs/product/ability-rollout-contract.md
* docs/product/mission-runtime-architecture-map.md
* docs/contracts/authority-ledger.v1.yaml
* docs/validation/live-runtime-matrix.md if proof meaning changes
* scripts/validation/ability_rollout_contract_check.py if validation rules change

Do not overclaim:
This PR completes the Capability / Ability Runtime Promotion lane.
It does not complete CRM/GTM provider activation.
It does not complete OAuth.
It does not complete credential refresh.
It does not complete secret management.
It does not complete durable third-party SaaS provider clients.
It does not replace ToolRuntimeAuthority or NetworkEgressAuthority.

Done means:

* Capability, adapter, and ability promotion semantics are complete and enforced.
* Declarative records cannot become runtime execution authority by accident.
* Concrete runtime authority flows through ToolRuntimeAuthority.
* External side-effect classifications remain exact.
* Tenant scope, disabled state, approval, idempotency, evidence, and readback rules are proven.
* Tests prove the completed lane.
* Docs/ledger/validation match implementation.
* No fake proof paths remain.
* CI is green.
