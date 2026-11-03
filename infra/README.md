# Ajenda AI — Infrastructure as Code

This directory contains Terraform modules for deploying Ajenda AI to AWS. The architecture is designed for multi-tenant SaaS operation with high availability, security-first configuration, and cost-efficient scaling.

**Code-aligned system map:** [`docs/architecture/SYSTEM_ARCHITECTURE.md`](../docs/architecture/SYSTEM_ARCHITECTURE.md)

**Deployment status (current `main`):**

- Defines the intended ECS Fargate task-definition and network foundation. It is
  not proof of an AWS deployment or production readiness.
- The controlled hosted release path is immutable artifacts → dormant service
  definitions → dedicated migrator task → schema verification → API/worker/
  assurance/frontend service promotion. Terraform creates services at zero
  desired count; `deploy/scripts/ecs-promote.sh` is the only path that starts
  them.
- Terraform does not create secret values, bootstrap database roles, run
  migrations, or promote services.
- Workers support `AJENDA_WORKER_TENANT_MODE=multi` (round-robin active tenants) or `single` (one `AJENDA_WORKER_TENANT_ID`) — see ADR-0004.
- Self-serve onboarding requires Resend email + `AJENDA_SIGNUP_VERIFY_URL_BASE` pointing at the deployed frontend `/verify-email` route.
- Stripe secrets: see `deploy/k8s/secret.example.yaml` and `docs/deployment/production-env-contract.md`.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  AWS Region (us-east-1 / eu-west-1)                             │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  VPC (10.0.0.0/16)                                       │    │
│  │                                                           │    │
│  │  Public Subnets (3 AZs)    Private Subnets (3 AZs)      │    │
│  │  ┌──────────────┐          ┌──────────────────────────┐  │    │
│  │  │ ALB           │          │ ECS Fargate              │  │    │
│  │  │ (HTTPS/443)   │──────▶  │ API Service (2-10 tasks) │  │    │
│  │  └──────────────┘          │ Worker Service (1-20)    │  │    │
│  │                             └──────────┬───────────────┘  │    │
│  │                                        │                   │    │
│  │                             ┌──────────▼───────────────┐  │    │
│  │                             │ RDS PostgreSQL 16         │  │    │
│  │                             │ (Multi-AZ, encrypted)    │  │    │
│  │                             └──────────────────────────┘  │    │
│  │                                        │                   │    │
│  │                             ┌──────────▼───────────────┐  │    │
│  │                             │ ElastiCache Redis 7       │  │    │
│  │                             │ (TLS, encrypted at rest)  │  │    │
│  │                             └──────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  AWS Secrets Manager — externally provisioned runtime secrets     │
│  GHCR or approved registry promotion — immutable image digests    │
│  CloudWatch — Logs, metrics, alarms                               │
└─────────────────────────────────────────────────────────────────┘
```

## Module Structure

```
infra/
├── modules/
│   ├── vpc/          — VPC, subnets, NAT gateways, security groups
│   ├── rds/          — PostgreSQL 16 RDS instance (Multi-AZ)
│   ├── redis/        — ElastiCache Redis 7 replication group
│   ├── ecs/          — ECS cluster, task definitions, services, ALB
│   └── secrets/      — existing secret-ARN policy and ECS injection access
├── environments/
│   ├── staging/      — Staging environment (smaller instances, single-AZ)
│   └── production/   — Production environment (Multi-AZ, larger instances)
└── README.md
```

## Prerequisites

- Terraform >= 1.7.0
- AWS CLI configured with appropriate credentials
- An existing Route 53 hosted zone (for the ALB certificate)
- Existing immutable OCI images and Secrets Manager secret references. The
  repository's release owner currently publishes GHCR artifacts; any ECR copy
  or GHCR pull strategy must preserve the exact digest.

## Deployment

```bash
# Foundation only: creates network, RDS, and Redis/Valkey. Runtime stays off.
cd infra/environments/staging
terraform init
terraform plan -out=tfplan
terraform apply tfplan

# Runtime task definitions require reviewed secret ARNs and immutable image
# digests, then promotion through deploy/scripts/ecs-promote.sh. Do not use
# terraform apply itself as a release action.
cd infra/environments/production
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

## Security Posture

All infrastructure is deployed with a security-first configuration:

- **Network isolation**: API and worker services run in private subnets with no direct internet access. Outbound traffic routes through NAT gateways.
- **Encryption at rest**: RDS and ElastiCache use AWS-managed KMS keys. S3 buckets use SSE-S3.
- **Encryption in transit**: ALB enforces TLS 1.2+. RDS and Redis require TLS connections.
- **Secrets management**: Terraform accepts secret ARNs, never secret values. ECS injects approved values from AWS Secrets Manager at task start; no plaintext credential is stored in Terraform variables or task-definition source.
- **Least privilege IAM**: Each ECS task has a dedicated IAM role with only the permissions it needs.
- **Security groups**: Principle of least privilege — only the ports and sources required for each service.

## State Management

Terraform state is stored in S3 with DynamoDB locking. Create the backend resources before first `terraform init`:

```bash
# Create state bucket (one-time, per AWS account)
aws s3api create-bucket \
  --bucket ajenda-ai-terraform-state-<account-id> \
  --region us-east-1

aws s3api put-bucket-versioning \
  --bucket ajenda-ai-terraform-state-<account-id> \
  --versioning-configuration Status=Enabled

aws dynamodb create-table \
  --table-name ajenda-ai-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

## Required external release inputs

The runtime phase is intentionally blocked until an operator supplies all of
the following outside Terraform state:

1. Immutable API, worker, assurance, migrator, and optional frontend image
   digests from the reviewed release.
2. Four distinct database URLs for `ajenda_api`, `ajenda_worker`,
   `ajenda_assurance`, and `ajenda_migrator`, created by the separately
   authorized database-role bootstrap procedure.
3. ARNs for those URLs and for the queue/encryption/runtime secrets required
   by the API and worker. The assurance and migrator task definitions receive
   only their role-specific database URL.
4. A reviewed registry-pull mechanism if the selected registry is not publicly
   accessible to ECS.

The RDS master secret created by AWS is foundation administration material; it
is not a runtime credential and must not be injected into API, worker, or
assurance tasks. ElastiCache is currently private-network and TLS protected.
If Redis AUTH is required for the selected environment, its configuration and
secret rotation must be added as a separately reviewed contract rather than
placing an auth token in Terraform state.
