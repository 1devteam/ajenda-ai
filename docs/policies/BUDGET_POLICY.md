# Mission Budget Policy (Bundle 5.2 Scaffolding)

## Scope

This policy defines the initial **observe-only** budget-governance contract for mission-stage economics.

- Bundle phase: **5.2**
- Enforcement mode: **observe-only**
- Runtime authority impact: **none** (no admission blocking)

## Feature flags and runtime controls

Budget-policy behavior is controlled by these runtime settings flags:

- `AJENDA_BUDGET_POLICY_ENABLED`
  - Enables budget-policy scaffolding surfaces and telemetry wiring.
  - Default: `false`
- `AJENDA_BUDGET_POLICY_OBSERVE_ONLY`
  - When `true`, captures policy observations and emits observability signals without mutating runtime admission/dispatch behavior.
  - Default: `true`
- `AJENDA_BUDGET_POLICY_ENFORCE`
  - Reserved for Bundle 5.3+ controlled enforcement rollouts.
  - Must remain `false` for Bundle 5.2.

## Guardrails

1. Observe-only mode must not block mission intake, runtime admission, worker claim/start/run, or queue dispatch.
2. Budget observations must be tenant-scoped and auditable.
3. Budget enforcement must be explicit, feature-flagged, and introduced only in a later bundle.
4. Rollback is config-first by disabling `AJENDA_BUDGET_POLICY_ENABLED` and keeping enforce off.

## Rollout notes

- Recommended Bundle 5.2 posture:
  - `AJENDA_BUDGET_POLICY_ENABLED=true`
  - `AJENDA_BUDGET_POLICY_OBSERVE_ONLY=true`
  - `AJENDA_BUDGET_POLICY_ENFORCE=false`
- If `AJENDA_BUDGET_POLICY_ENFORCE=true`, `AJENDA_BUDGET_POLICY_ENABLED` must also be true.
- Enforced mode and policy-denial behavior are out of scope for this bundle.


## Runtime Authority Guarantee

- Bundle 5.2 budget policy flags are runtime-authority configuration scaffolding only and remain inert by default.
- No mission intake, runtime admission, queue dispatch, worker claim/start/run, or lease/recovery execution path is altered by these flags in Bundle 5.2.
- No budget-policy enforcement behavior exists in Bundle 5.2.
- Bundle 5.3 (or later) must separately implement and prove enforcement behavior with targeted runtime and policy contract evidence.
