# Intelligence foundation Pass 1 — deterministic coverage expansion

## Scope

This pass expands the deterministic local-fixture coverage catalog to match the
industry overlays already declared by the semantic lattice. It centralizes
fixture scope authority in `ajenda_demo_fixtures.local_fixture_scope_keys()`;
composition no longer maintains a second hard-coded allow-list.

The catalog now has three deterministic fixture accounts for each of these
additional scopes: advertising/Austin, electrical/Austin, landscaping/Austin,
pest control/Austin, legal/Austin, dental/Austin, recruiting/Austin, SaaS/Austin,
and e-commerce/Austin. Existing software development/Austin, HVAC/Dallas,
roofing/Austin, plumbing/Austin, and professional-services/Austin scopes remain.
The `software/Austin` interpreter alias remains supported without duplicating
records.

Fixtures are evidence-class `local_fixture`; they are not live-world entities,
provider observations, or authority to execute actions.

## Fail-closed behavior

An explicitly requested fixture scope without catalog records remains
`unsupported_scope` and cannot become runtime work. Requests above a known
scope's capacity remain `insufficient_capacity`. Public/provider and tenant
internal CRM sources remain `unknown` at composition until runtime observation
or an explicit internal capacity snapshot is supplied.

## Proof

- Targeted coverage, composition, deliverable-read-model, and action-input tests: passed.
- Full non-integration suite (`tests/unit`, `tests/contract`, `tests/deployment`): passed.
- Ruff, formatting, mypy, contract, authority, migration, ability, and
  GRAFT1st-reconciliation validators: passed.
- GRAFT+ gate: 9/9 steps passed.
- Changed-file impact: 6 files, 28 changed nodes, 206 impacted tests, 4
  invariants, 0 unmapped files; risk domain `action-contract`.
- Canonical graph regenerated: 1,619 nodes and 4,659 edges.

The rebuilt Docker live-proof image was not completed in this pass because its
Chromium dependency installation was intentionally stopped. Therefore this
document does not claim a new live runtime artifact; the existing live proof
remains valid for the previously supported scopes. A rebuilt-stack proof for a
new scope is the next runtime verification step.

## Deliberately deferred

Provider/CRM capacity discovery, epistemic calibration, semantic business-goal
comparison, shadow execution, and onboarding/UI work remain outside this slice.
