## Summary

<!-- One paragraph describing what this PR does and why. -->

## Type of Change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Refactor (no functional change)
- [ ] Documentation update
- [ ] CI/CD / infrastructure change

## Pre-Merge Checklist (Pride Protocol)

- [ ] Read all relevant files completely before making changes
- [ ] Understood the full problem and context — no assumptions made
- [ ] Planned a complete solution, not a patch
- [ ] All new code has type hints and docstrings
- [ ] Tests added or updated for all changed behaviour
- [ ] `ruff check` and `ruff format` pass locally
- [ ] `mypy` passes locally
- [ ] `pytest tests/unit/ tests/contract/ tests/deployment/` passes locally
- [ ] Migration added if schema changed, with downgrade path verified
- [ ] Schema/data seed changes prove JSONB seed-shape parity with API/domain contracts
- [ ] RLS-backed seed migrations prove same-role downgrade behavior and no temporary policy residue
- [ ] No secrets or credentials committed
- [ ] Commit messages follow `type(scope): description` convention

## Ability / Tool Rollout Checklist

<!-- Required for PRs that add or change capabilities, adapters, `tool.invoke` actions,
     providers, side-effect behavior, action schemas, evidence bridges, or runtime tool authority.
     Leave unchecked items with a short N/A explanation when the PR does not touch abilities/tools. -->

- [ ] Action/capability/adapter names are stable and searched for all existing references
- [ ] New or changed action has a Pydantic input model or documented no-input contract
- [ ] Action returns `ActionResult` and emits success-path `EvidenceItem` output
- [ ] Side-effect class is explicit and matches actual handler behavior
- [ ] Side-effecting actions require `execution_constraints.side_effect_authorization`
- [ ] Side-effecting actions require concrete capability and/or adapter authority
- [ ] External writes/sends/publishes include idempotency and retry-safety proof
- [ ] Capability and adapter metadata remain declarative and do not register runtime handlers directly
- [ ] Tenant scope is validated before reads, writes, and evidence persistence
- [ ] Tests cover happy path, unauthorized path, tenant mismatch, malformed input, and relevant failure/retry behavior
- [ ] Migration/domain/Pydantic/schema parity is preserved when persisted contracts change

## Test Coverage

<!-- Describe what tests were added and what they cover. -->

## Migration Notes

<!-- If this PR includes a database migration, describe the migration, rollback path,
     deployment ordering requirements (e.g., must deploy before traffic), JSONB seed-shape
     parity evidence, same-role downgrade proof, and temporary RLS policy residue checks. -->

## Breaking Changes

<!-- If this PR introduces breaking changes, describe the impact and migration path. -->
