# Rollback

1. Confirm the incident through health, readiness, logs, metrics, and durable
   runtime evidence.
2. Identify the previous exact API, worker, assurance, and optional frontend
   task-definition revisions. A tag is not sufficient identity.
3. Establish and record that those runtime images are compatible with the
   currently applied schema. An ECS service rollback does not undo a migration.
4. Set `AJENDA_ECS_SCHEMA_COMPATIBILITY_APPROVED=1` only after that review, then
   run `deploy/scripts/ecs-rollback.sh` with the exact service/task definition
   inputs.
5. Verify readiness and run the appropriate target proof.
6. If the prior runtime is not schema-compatible, do not roll it back. Use a
   controlled forward-fix or separately reviewed database recovery plan.

The Kubernetes helper at `deploy/scripts/rollback.sh` is reference-only and is
not the hosted Ajenda rollback path.
