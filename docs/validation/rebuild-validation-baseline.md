# Rebuild Validation Baseline

Authoritative commands for the rebuild line:

- ruff check backend/ tests/
- ruff format --check backend/ tests/
- pytest -q tests/unit/ tests/contract/
- pytest -q

Focused pull request proof may be used for narrow slices, but it must not be described as full repository health.

Current known stale-test areas to align:

- integration fixture expectations
- auth app state setup
- SQLite tests against PostgreSQL UUID models
- OIDC constructor contract drift
- Redis tests that expect a live Redis service
