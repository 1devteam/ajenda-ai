# Rollback

1. Confirm deployment issue using health, readiness, and metrics.
2. Scale down unhealthy workers if required.
3. Roll back api and worker image tags to last known good release.
4. Confirm schema compatibility before rollback if migrations ran.
5. Re-run health and readiness verification.
