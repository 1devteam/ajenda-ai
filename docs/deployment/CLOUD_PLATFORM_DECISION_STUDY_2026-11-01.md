# Ajenda Cloud Platform Decision Study

**Status:** proposed platform decision; not deployment authorization  
**Date:** 2026-11-01  
**Evidence level:** repository source inspection plus vendor documentation. No cloud account,
target environment, provider credential, or live-cloud runtime was used in this study.

## Decision

Adopt **AWS ECS on Fargate** as Ajenda's intended long-term hosted runtime, with:

- ECS Fargate services for API, worker, assurance, and frontend;
- an explicit, one-off ECS migrator task;
- RDS for PostgreSQL as the durable relational store;
- ElastiCache for Redis/Valkey as the queue backing service;
- private task networking, Secrets Manager, KMS, ALB, CloudWatch, and Terraform;
- immutable release artifacts promoted only after migration and schema verification.

This decision does **not** authorize an AWS purchase, account creation, Terraform apply,
database migration, production deployment, or public cutover. Those are separately controlled
operations.

## Ajenda requirements that control the choice

Ajenda is not a request-only web application. The current source owns five distinct runtime
roles:

| Role | Existing source owner | Required platform property |
|---|---|---|
| API | `deploy/scripts/start-api.sh`, `backend.main:app` | stable HTTP service, readiness gate, private DB/queue access |
| Worker | `deploy/scripts/start-worker.sh`, `WorkerLoop` | continuously running queue consumer, outbound public research, Chromium support |
| Assurance | `deploy/scripts/start-assurance.sh` | independently deployable long-running runtime |
| Migrator | `deploy/scripts/run-migrations.sh` | explicit finite task, dedicated DB identity, schema-head verification |
| Frontend | `deploy/docker/frontend.Dockerfile` | HTTP service/CDN-compatible public delivery |

The source-of-truth release invariant is:

```text
one source revision
  -> immutable role-specific artifacts
  -> explicit migrator from that revision
  -> database proven at that revision's single Alembic head
  -> API, worker, assurance, and frontend promotion
  -> readiness and operator proof
```

Ajenda also requires tenant isolation, separate API/worker/assurance/migrator database
identities, queue/lease runtime authority, evidence persistence, browser containment, and
governed public-network access. A provider that merely runs a Python web process is therefore
not enough.

## Existing repository position

The repository already has the right broad AWS ownership boundaries:

- `infra/modules/vpc`, `rds`, `redis`, `secrets`, and `ecs`;
- staging and production Terraform roots;
- role-specific API, worker, and migrator images in release CI;
- a Compose reference environment that correctly gates API, worker, and assurance on the
  dedicated migrator's successful completion;
- runtime startup checks that fail closed when the database does not report the image's expected
  Alembic head.

It is not deployable as-is. The AWS ECS task definitions still use legacy environment names,
a nonexistent `backend.worker` entrypoint, a shared administrative database identity, one image
for incompatible roles, and lack dedicated migrator and assurance task definitions. Terraform
currently cannot be treated as a valid Ajenda release path. Those are CDE remediation items,
not reasons to discard the AWS foundation.

## Options considered

| Option | Fit | Decision |
|---|---|---|
| AWS ECS/Fargate + RDS + ElastiCache | Directly models service, worker, assurance, and one-off migration task; existing Terraform/VPC work is reusable; strongest current fit for private networking and role separation. | **Select** |
| Google Cloud Run + Cloud SQL + Memorystore | Technically viable: Cloud Run has HTTP services, jobs, and worker pools. Requires a new infrastructure, IAM, networking, artifact-promotion, and runbook implementation with no Ajenda foundation today. | Viable alternative, not selected |
| Render | Good low-friction staging candidate: web services, continuous workers, cron jobs, Postgres, and Redis-compatible Key Value. It does not reuse Ajenda's existing CDE foundation and gives less control over the network/identity model required for the durable production target. | Do not make canonical |
| DigitalOcean App Platform | Can run Docker-based services, workers, and jobs. Same issue: a new delivery/security model would be required and no current Ajenda proof exists. | Do not make canonical |
| Kubernetes/EKS | Flexible, but adds cluster control-plane, upgrade, policy, and operations burdens. Existing manifests are incomplete and unconnected to release promotion. | Explicitly defer |
| Compose only | The only current end-to-end proof surface. It remains the local/isolated reference environment, not a hosted production platform. | Retain as proof surface |

## Why ECS/Fargate is the appropriate target

ECS task definitions explicitly support both services and individually run tasks. That maps to
Ajenda's continuously maintained API/worker/assurance runtimes and its finite migrator without
inventing another scheduler. ECS service deployment health and rollback are useful for runtime
rollout failures, but cannot establish backward database compatibility after a migration; the
migration-first Ajenda release controller remains authoritative.

Fargate is suitable for Ajenda's Linux container images and lets each task run with private VPC
networking. The worker's Chromium image must be validated in a real Fargate staging task before
production use; source presence and local Docker proof are not cloud-runtime proof.

RDS PostgreSQL preserves actual PostgreSQL semantics necessary for Alembic, RLS, roles,
transactions, and tenant tests. Production should use an availability design justified by the
launch SLO; it must not simply inherit the existing `db.r8g.large` placeholder. ElastiCache
provides a managed Redis-compatible queue store; enabling TLS requires client compatibility proof
and must not silently weaken Ajenda queue reliability.

## Target deployment shape

```text
public user
  -> DNS / ACM certificate / ALB
  -> frontend service and API service

private subnets
  -> worker service (Chromium-capable, governed outbound egress)
  -> assurance service
  -> explicit migrator RunTask
  -> RDS PostgreSQL
  -> ElastiCache Redis/Valkey
  -> VPC endpoints where applicable
  -> NAT only for approved public outbound traffic

Secrets Manager + KMS
  -> role-specific task secret injection
```

The browser worker and ordinary worker may initially remain the same service only if task sizing,
isolation, and scaling proof supports that. Otherwise, separate the browser-capable worker into a
distinct ECS service using the existing execution authority and action policy, not a bypass.

## Release and rollback contract

1. CI builds role-specific immutable images from one source SHA and records their digests.
2. The operator or controlled deployment workflow selects those exact digests; mutable `latest`
   must never be a promotion input.
3. An explicit migrator task uses the migrator database identity, runs `run-migrations.sh`, and
   proves the expected single Alembic head.
4. Only after that proof succeeds may API, worker, and assurance services update.
5. ECS health checks and deployment circuit breakers may roll back a failed *service revision*.
6. Database rollback is never inferred from an ECS rollback. A prior image can be restored only
   after a documented compatibility assessment, or a forward-fix is used.
7. Post-deploy proof validates external readiness, tenant-scoped execution, queue/lease cleanup,
   evidence persistence, and fresh-session operator readback.

## Security requirements for the AWS implementation

- All application tasks run in private subnets; only the ALB is public.
- The API, worker, assurance, and migrator use distinct database URLs and identities.
- Role bootstrap remains an explicit separately authorized operation; it is not an application
  startup action or routine migration dependency.
- Secrets enter task environments through protected secret references, not Terraform plaintext
  values stored in state or task definition literals.
- Egress remains governed in Ajenda's `NetworkEgressAuthority`; NAT is transport, not permission.
- Security groups restrict RDS/Redis to the minimum required task roles. The assurance and
  migrator path must be included deliberately rather than being accidentally blocked or granted
  broad access.
- Browser-capable tasks retain request-method, redirect, DNS/IP, and destination controls.
- Logs, artifacts, screenshots, and task diagnostics preserve Ajenda redaction obligations.

## Cost model and controls

Do not authorize on a guessed monthly total. Produce an AWS Pricing Calculator estimate after
selecting region, availability target, traffic, storage, retention, and expected public-research
egress. The material cost drivers are:

| Driver | Practical control |
|---|---|
| Always-on Fargate API, worker, assurance | Start staging at the smallest source-proven task shapes; measure CPU/memory before resizing. |
| Browser worker memory/CPU | Separate only after a real Fargate Chromium benchmark; never use Spot for work whose interruption semantics are not proven. |
| RDS instance, storage, backups, Multi-AZ | Single-AZ staging with backups; choose production HA only against an explicit availability target. |
| Redis/Valkey topology | Start with an appropriately sized staging node; choose replication/failover after queue-loss and recovery requirements are approved. |
| NAT gateways and research egress | NAT is billed by availability and data processed. Use VPC endpoints for AWS control-plane traffic and measure public-research egress. |
| Logs, metrics, tracing, backups | Set retention, sampling, alert, and budget policies before launch. |

The current Terraform's production three-NAT design can be justified for high availability, but it
is not an appropriate default before traffic and SLOs are known. Staging can use one NAT with an
explicit single-AZ failure-domain limitation.

## Required decisions before an AWS staging build

1. AWS account organization, billing owner, region, and environment naming.
2. Staging data classification and a prohibition on production customer data in staging.
3. Domain, DNS ownership, ACM certificate, and outbound-email provider configuration.
4. Initial availability objective and recovery objective for staging versus production.
5. Approved secret ownership/rotation model and encrypted Terraform-state operating model.
6. Browser-worker capacity limit and approved public-research egress budget.
7. Image registry decision: continue GHCR with authenticated ECS pulls, or copy verified digest
   artifacts into private ECR. The image digest—not the registry name—is the promotion identity.
8. Who is authorized to run role bootstrap, migrator, deploy, rollback, and data recovery.

## Preconditions for first authorized staging deployment

- [ ] CDE remediation is complete and its deployment contracts are green.
- [ ] ECS task definitions use the current Ajenda entrypoints and `AJENDA_*` contract.
- [ ] API, worker, assurance, and migrator have distinct task definitions, images/commands, and
      database identities.
- [ ] Terraform no longer receives application or database secret plaintext into state.
- [ ] Immutable artifact digest promotion is implemented and recorded.
- [ ] Migrator-first promotion and schema-head verification are executable and tested locally.
- [ ] Schema-aware rollback/forward-fix runbook exists and is reviewed.
- [ ] Real Fargate staging proof validates Chromium startup, Redis TLS, database roles/RLS,
      readiness, migration, queue/lease, evidence, and operator readback.
- [ ] AWS budget alarms, log retention, backups, least-privilege IAM, and incident contacts are
      configured.

## Vendor references

- AWS ECS task definitions: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definitions.html
- ECS deployment circuit breaker: https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_DeploymentCircuitBreaker.html
- Fargate task constraints: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-tasks-services.html
- RDS PostgreSQL availability and pricing: https://aws.amazon.com/rds/postgresql/pricing/
- ElastiCache TLS: https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/in-transit-encryption.html
- NAT pricing: https://docs.aws.amazon.com/vpc/latest/userguide/nat-gateway-pricing.html
- Cloud Run resource model: https://docs.cloud.google.com/run/docs/resource-model
- Render workers: https://render.com/docs/background-workers
- DigitalOcean App Platform workers: https://docs.digitalocean.com/products/app-platform/how-to/manage-workers/

## Non-goals

This study does not claim that AWS, Terraform, Kubernetes, GHCR, or any provider deployment is
currently production-ready. It does not change Ajenda's provider/browser governance, grant cloud
credentials, or replace the existing Compose proof surface.
