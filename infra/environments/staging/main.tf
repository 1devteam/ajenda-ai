###############################################################################
# Staging Environment — Ajenda AI
#
# Cost-optimised: single NAT gateway, single-AZ RDS, single Redis node,
# smaller instance sizes. Suitable for integration testing and pre-production.
###############################################################################

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "ajenda-ai-terraform-state"  # Replace with your account-specific bucket
    key            = "staging/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "ajenda-ai-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "ajenda-ai"
      Environment = "staging"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  name_prefix = "ajenda-staging"
  tags = {
    Project     = "ajenda-ai"
    Environment = "staging"
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Secrets (must be created first — other modules reference secret ARNs)
# ---------------------------------------------------------------------------

module "secrets" {
  source      = "../../modules/secrets"
  name_prefix = local.name_prefix

  db_password             = var.db_password
  redis_auth_token        = var.redis_auth_token
  oidc_signing_key_pem    = var.oidc_signing_key_pem
  webhook_hmac_master_key = var.webhook_hmac_master_key

  tags = local.tags
}

# ---------------------------------------------------------------------------
# VPC
# ---------------------------------------------------------------------------

module "vpc" {
  source      = "../../modules/vpc"
  name_prefix = local.name_prefix

  vpc_cidr             = "10.1.0.0/16"
  availability_zones   = ["us-east-1a", "us-east-1b"]
  public_subnet_cidrs  = ["10.1.1.0/24", "10.1.2.0/24"]
  private_subnet_cidrs = ["10.1.11.0/24", "10.1.12.0/24"]
  single_nat_gateway   = true  # Cost saving for staging

  tags = local.tags
}

# ---------------------------------------------------------------------------
# RDS
# ---------------------------------------------------------------------------

module "rds" {
  source      = "../../modules/rds"
  name_prefix = local.name_prefix

  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_id  = module.vpc.sg_rds_id

  instance_class           = "db.t4g.small"
  allocated_storage_gb     = 20
  max_allocated_storage_gb = 50
  multi_az                 = false  # Single-AZ for staging
  backup_retention_days    = 3
  deletion_protection      = false

  db_name     = "ajenda"
  db_username = "ajenda_admin"
  db_password = var.db_password

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------

module "redis" {
  source      = "../../modules/redis"
  name_prefix = local.name_prefix

  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_id  = module.vpc.sg_redis_id

  node_type          = "cache.t4g.small"
  num_cache_clusters = 1  # Single node for staging
  auth_token         = var.redis_auth_token

  tags = local.tags
}

# ---------------------------------------------------------------------------
# ECS
# ---------------------------------------------------------------------------

module "ecs" {
  source      = "../../modules/ecs"
  name_prefix = local.name_prefix
  environment = "staging"
  aws_region  = var.aws_region

  vpc_id             = module.vpc.vpc_id
  public_subnet_ids  = module.vpc.public_subnet_ids
  private_subnet_ids = module.vpc.private_subnet_ids
  sg_alb_id          = module.vpc.sg_alb_id
  sg_ecs_api_id      = module.vpc.sg_ecs_api_id
  sg_ecs_worker_id   = module.vpc.sg_ecs_worker_id

  acm_certificate_arn     = var.acm_certificate_arn
  ecr_image_uri           = var.ecr_image_uri
  image_tag               = var.image_tag
  secrets_read_policy_arn = module.secrets.ecs_secrets_read_policy_arn

  db_host    = module.rds.db_host
  db_port    = module.rds.db_port
  db_name    = module.rds.db_name
  db_username = "ajenda_admin"
  redis_host = module.redis.primary_endpoint

  db_password_secret_arn      = module.secrets.db_password_secret_arn
  redis_auth_token_secret_arn = module.secrets.redis_auth_token_secret_arn
  oidc_signing_key_secret_arn = module.secrets.oidc_signing_key_secret_arn

  # Smaller capacity for staging
  api_cpu           = 256
  api_memory        = 512
  api_desired_count = 1
  api_min_count     = 1
  api_max_count     = 3

  worker_cpu           = 512
  worker_memory        = 1024
  worker_desired_count = 1
  worker_min_count     = 1
  worker_max_count     = 5

  log_level          = "DEBUG"
  log_retention_days = 7

  tags = local.tags
}
