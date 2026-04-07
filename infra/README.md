# Ajenda AI — Infrastructure as Code

This directory contains Terraform modules for deploying Ajenda AI to AWS. The architecture is designed for multi-tenant SaaS operation with high availability, security-first configuration, and cost-efficient scaling.

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
│  │                             │ (Cluster mode, encrypted) │  │    │
│  │                             └──────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  AWS Secrets Manager — DB password, Redis auth token, OIDC keys  │
│  ECR — Docker image registry                                      │
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
│   └── secrets/      — AWS Secrets Manager secrets and IAM policies
├── environments/
│   ├── staging/      — Staging environment (smaller instances, single-AZ)
│   └── production/   — Production environment (Multi-AZ, larger instances)
└── README.md
```

## Prerequisites

- Terraform >= 1.7.0
- AWS CLI configured with appropriate credentials
- An existing Route 53 hosted zone (for the ALB certificate)
- An existing ECR repository with the Ajenda AI Docker image

## Deployment

```bash
# Staging
cd infra/environments/staging
terraform init
terraform plan -out=tfplan
terraform apply tfplan

# Production
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
- **Secrets management**: No credentials in environment variables or task definitions. All secrets are fetched from AWS Secrets Manager at container startup via ECS secrets injection.
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
