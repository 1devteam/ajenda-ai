# Revenue Operations Know-How V1

**Contract ID:** `revops.research-to-approved-outreach`  
**Version:** `1.0.0`  
**Authority:** declarative; never executable authority  
**Promotion:** blocked pending owner-approved numeric budgets and release thresholds

## Responsibility

The implementation in `backend/services/mission_composition/vertical_know_how.py` pins the selected
Revenue Operations workflow to a versioned set of existing business jobs, stage dependencies,
deliverable producer fields, connector references, prohibited actions, and review boundaries. It
constrains later planning work without registering handlers, resolving credentials, issuing
approval, creating tasks, or touching the queue.

Revenue Operations composition records carry the exact know-how ID and version in
`composition_provenance`. Unsupported or mixed-vertical outcome sets do not acquire this reference.
Unknown future versions fail closed through `get_vertical_know_how`.

## Validation

Contract construction rejects duplicate stages/jobs, unknown jobs/connectors, dependency cycles,
missing deliverable producers, incomplete version references, and promotion without a budget.
`validate_know_how_runtime_references` additionally verifies each referenced candidate action
against the existing action registry, Pydantic input contract, ability manifest, side-effect
classification, approval/idempotency requirements, and stage review boundary.

The validator reads authoritative catalogs. It does not create a shadow job/action catalog and has
no invocation or persistence path.

## Compatibility and rollback

The contract is additive and versioned. A proposal/mission retains the version stored in its
composition provenance; later versions must be added alongside `1.0.0`, not silently substituted.
Rollback stops selecting a new version while retaining the old contract for existing records.
Deleting an in-use version is forbidden because reconstruction must fail visibly rather than
reinterpret an active mission.

The current contract cannot become `eligible` until its `KnowHowBudget` values and D8 promotion
thresholds are explicitly owner-approved. Optional Gmail delivery and HubSpot updates remain behind
independent approval, credentials, canonical runtime admission, and provider effect proof.
