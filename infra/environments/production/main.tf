###############################################################################
# Production Environment — Ajenda AI
#
# High availability: 3-AZ VPC, Multi-AZ RDS, 2-node Redis with failover,
# production-grade instance sizes, deletion protection enabled.
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
    key            = "production/terraform.tfstate"
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
      Environment = "production"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  name_prefix = "ajenda-prod"
  tags = {
    Project     = "ajenda-ai"
    Environment = "production"
    ManagedBy   = "terraform"
  }
}

# ---------------------------------------------------------------------------
# Secrets
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
# VPC — 3 AZs for production
# ---------------------------------------------------------------------------

module "vpc" {
  source      = "../../modules/vpc"
  name_prefix = local.name_prefix

  vpc_cidr             = "10.0.0.0/16"
  availability_zones   = ["us-east-1a", "us-east-1b", "us-east-1c"]
  public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  private_subnet_cidrs = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
  single_nat_gateway   = false  # One NAT per AZ for production HA

  flow_log_retention_days = 90

  tags = local.tags
}

# ---------------------------------------------------------------------------
# RDS — Multi-AZ
# ---------------------------------------------------------------------------

module "rds" {
  source      = "../../modules/rds"
  name_prefix = local.name_prefix

  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_id  = module.vpc.sg_rds_id

  instance_class           = "db.r8g.large"
  allocated_storage_gb     = 100
  max_allocated_storage_gb = 1000
  multi_az                 = true
  backup_retention_days    = 30
  deletion_protection      = true

  db_name     = "ajenda"
  db_username = "ajenda_admin"
  db_password = var.db_password

  max_connections_alarm_threshold = 500
  alarm_sns_arn                   = var.alarm_sns_arn

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Redis — 2-node replication group with automatic failover
# ---------------------------------------------------------------------------

module "redis" {
  source      = "../../modules/redis"
  name_prefix = local.name_prefix

  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_id  = module.vpc.sg_redis_id

  node_type          = "cache.r7g.large"
  num_cache_clusters = 2  # Primary + replica for automatic failover
  auth_token         = var.redis_auth_token

  snapshot_retention_days = 7
  alarm_sns_arn           = var.alarm_sns_arn

  tags = local.tags
}

# ---------------------------------------------------------------------------
# ECS — Production sizing
# ---------------------------------------------------------------------------

module "ecs" {
  source      = "../../modules/ecs"
  name_prefix = local.name_prefix
  environment = "production"
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

  db_host     = module.rds.db_host
  db_port     = module.rds.db_port
  db_name     = module.rds.db_name
  db_username = "ajenda_admin"
  redis_host  = module.redis.primary_endpoint

  db_password_secret_arn      = module.secrets.db_password_secret_arn
  redis_auth_token_secret_arn = module.secrets.redis_auth_token_secret_arn
  oidc_signing_key_secret_arn = module.secrets.oidc_signing_key_secret_arn

  # Production capacity
  api_cpu           = 1024
  api_memory        = 2048
  api_desired_count = 2
  api_min_count     = 2
  api_max_count     = 10

  worker_cpu           = 2048
  worker_memory        = 4096
  worker_desired_count = 2
  worker_min_count     = 1
  worker_max_count     = 20

  log_level          = "INFO"
  log_retention_days = 90

  enable_deletion_protection = true
  alb_access_logs_bucket     = var.alb_access_logs_bucket

  tags = local.tags
}
