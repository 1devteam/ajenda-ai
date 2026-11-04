# Deployment

## Scope

Compose remains Ajenda's locally proven deployment and runtime-proof surface.
AWS ECS is the intended hosted target. Kubernetes manifests are reference-only,
not a release procedure.

## ECS controlled promotion

1. Select one source revision and record immutable OCI digests for API, worker,
   assurance, migrator, and frontend artifacts.
2. Apply reviewed Terraform only to create/update infrastructure and task
   definition revisions. Terraform does not promote a release.
3. Separately authorize any database role bootstrap. Do not run it as a normal
   migration or application-startup step.
4. Confirm the role-specific connection URL and required runtime secret ARNs
   already exist in Secrets Manager.
5. Set the exact ECS cluster, service names, network configuration, task
   definition ARNs, API base URL, and `AJENDA_ECS_PROMOTION_APPROVED=1`.
   The promotion environment must also declare positive API, worker, and
   assurance desired counts; API and worker must declare a capacity range with
   `minimum <= desired <= maximum`. Those values are promotion controls, not
   Terraform inputs: services are deliberately created dormant at zero until
   the migrator succeeds.
6. Run `deploy/scripts/ecs-promote.sh`. It runs the dedicated migrator task,
   waits for its zero exit, then updates API, worker, assurance, and optional
   frontend services.
7. Run the target-specific post-deploy mission proof and inspect durable
   evidence/readback. ECS readiness alone is not commercial-runtime proof.

Do not use mutable image tags, `terraform apply` as a release command, or an
application service to apply migrations.
