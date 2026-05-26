# Budget Policy Runtime Authority Contract (Bundle 5.2)

## Contract scope

This contract classifies Bundle 5.2 budget policy flags as **runtime-authority configuration scaffolding**.

- `AJENDA_BUDGET_POLICY_ENABLED`
- `AJENDA_BUDGET_POLICY_OBSERVE_ONLY`
- `AJENDA_BUDGET_POLICY_ENFORCE`

## Bundle 5.2 authority posture

- Default state is **disabled/inert**: `enabled=false`, `observe_only=true`, `enforce=false`.
- Observe-only state is **non-mutating**: `enabled=true`, `observe_only=true`, `enforce=false`.
- Enforcement state is **reserved for later bundles**: `enabled=true`, `observe_only=false`, `enforce=true`.

Bundle 5.2 does not authorize admission, execution, or policy enforcement changes.

## Invalid configuration combinations

`Settings.validate_runtime_contract()` must fail fast for:

1. `enabled=false` and `enforce=true`
2. `observe_only=true` and `enforce=true`
3. `enabled=false` and `observe_only=false`

## Runtime-path guarantee

In Bundle 5.2, no runtime path may branch on budget policy flags outside runtime settings validation and non-runtime docs/tests/deployment scaffolding.

Forbidden in Bundle 5.2:

- mission admission branching
- task/queue dispatch branching
- worker claim/start/run branching
- lease lifecycle branching
- runtime enforcement decisions
