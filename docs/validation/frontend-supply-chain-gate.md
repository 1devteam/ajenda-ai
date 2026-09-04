# Frontend Supply-Chain Gate

## Design note

The frontend product console introduces a Node/Vite dependency graph under `frontend/`.
That graph must be treated as a release-gated supply-chain surface, not an operator-only local build concern.

This bundle adds:

- Dependabot npm monitoring for `/frontend`
- CI frontend dependency install and production build
- scheduled/manual/PR security workflow npm audit coverage
- deployment contract tests proving those gates remain wired

## Authority and risk class

Risk class: release-gate / supply-chain hardening.

This change does not add runtime authority, queue admission authority, worker lease authority, or tenant mutation behavior.
It only expands proof surfaces required before promotion.

## Backward compatibility

No API, database, queue, mission, runtime, tenant, or evidence schema is changed.

Existing backend gates remain intact.
The frontend gate is additive and fails closed when the frontend dependency graph or build becomes unsafe.

## Validation impact

Required validation:

- frontend `npm ci`
- frontend `npm audit` (dedicated security workflow)
- frontend `npm run build`
- deployment contract tests for CI/security/Dependabot wiring
- existing Python lint, type, contract, migration, and test gates

## Rollback strategy

Rollback by removing:

- the `/frontend` npm entry from `.github/dependabot.yml`
- the `frontend-build` job from `.github/workflows/ci.yml`
- the `npm-audit` job from `.github/workflows/security.yml`
- the deployment contract test added for this gate

Rollback does not require database migration or runtime data repair.
