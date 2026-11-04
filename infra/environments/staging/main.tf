terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  backend "s3" {
    bucket         = "ajenda-ai-terraform-state"
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

module "vpc" {
  source               = "../../modules/vpc"
  name_prefix          = local.name_prefix
  vpc_cidr             = "10.1.0.0/16"
  availability_zones   = ["us-east-1a", "us-east-1b"]
  public_subnet_cidrs  = ["10.1.1.0/24", "10.1.2.0/24"]
  private_subnet_cidrs = ["10.1.11.0/24", "10.1.12.0/24"]
  single_nat_gateway   = true
  tags                 = local.tags
}

module "rds" {
  source                   = "../../modules/rds"
  name_prefix              = local.name_prefix
  private_subnet_ids       = module.vpc.private_subnet_ids
  security_group_id        = module.vpc.sg_rds_id
  instance_class           = "db.t4g.small"
  allocated_storage_gb     = 20
  max_allocated_storage_gb = 50
  multi_az                 = false
  backup_retention_days    = 3
  deletion_protection      = false
  db_name                  = "ajenda"
  db_username              = "ajenda_admin"
  tags                     = local.tags
}

module "redis" {
  source             = "../../modules/redis"
  name_prefix        = local.name_prefix
  private_subnet_ids = module.vpc.private_subnet_ids
  security_group_id  = module.vpc.sg_redis_id
  node_type          = "cache.t4g.small"
  num_cache_clusters = 1
  tags               = local.tags
}

# Data-plane foundation is intentionally independent from runtime promotion.
# Enable this only after external secret references and immutable release image
# digests have been created and reviewed.
module "secrets" {
  count       = var.enable_runtime ? 1 : 0
  source      = "../../modules/secrets"
  name_prefix = local.name_prefix
  secret_arns_by_runtime = {
    api       = toset(concat(values(var.runtime_secret_arns), [var.api_database_url_secret_arn]))
    worker    = toset(concat(values(var.runtime_secret_arns), [var.worker_database_url_secret_arn]))
    assurance = toset([var.assurance_database_url_secret_arn])
    migrator  = toset([var.migrator_database_url_secret_arn])
  }
  tags = local.tags
}

module "ecs" {
  count                             = var.enable_runtime ? 1 : 0
  source                            = "../../modules/ecs"
  name_prefix                       = local.name_prefix
  environment                       = "staging"
  aws_region                        = var.aws_region
  vpc_id                            = module.vpc.vpc_id
  public_subnet_ids                 = module.vpc.public_subnet_ids
  private_subnet_ids                = module.vpc.private_subnet_ids
  sg_alb_id                         = module.vpc.sg_alb_id
  sg_ecs_api_id                     = module.vpc.sg_ecs_api_id
  sg_ecs_worker_id                  = module.vpc.sg_ecs_worker_id
  sg_ecs_frontend_id                = module.vpc.sg_ecs_frontend_id
  acm_certificate_arn               = var.acm_certificate_arn
  secrets_read_policy_arns          = module.secrets[0].ecs_secrets_read_policy_arns
  api_database_url_secret_arn       = var.api_database_url_secret_arn
  worker_database_url_secret_arn    = var.worker_database_url_secret_arn
  assurance_database_url_secret_arn = var.assurance_database_url_secret_arn
  migrator_database_url_secret_arn  = var.migrator_database_url_secret_arn
  runtime_environment               = var.runtime_environment
  runtime_secret_arns               = var.runtime_secret_arns
  api_image                         = var.api_image
  worker_image                      = var.worker_image
  assurance_image                   = var.assurance_image
  migrator_image                    = var.migrator_image
  frontend_image                    = var.frontend_image
  api_cpu                           = 256
  api_memory                        = 512
  api_max_count                     = 3
  worker_cpu                        = 512
  worker_memory                     = 1024
  worker_max_count                  = 5
  assurance_cpu                     = 256
  assurance_memory                  = 512
  frontend_cpu                      = 256
  frontend_memory                   = 512
  log_retention_days                = 7
  tags                              = local.tags
}
