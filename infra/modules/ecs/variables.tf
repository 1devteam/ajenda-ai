variable "name_prefix" {
  description = "Prefix for all resource names"
  type        = string
}

variable "environment" {
  description = "Environment name (staging or production)"
  type        = string
}

variable "aws_region" {
  description = "AWS region for CloudWatch log configuration"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID"
  type        = string
}

variable "public_subnet_ids" {
  description = "IDs of public subnets for the ALB"
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "IDs of private subnets for ECS tasks"
  type        = list(string)
}

variable "sg_alb_id" {
  description = "Security group ID for the ALB"
  type        = string
}

variable "sg_ecs_api_id" {
  description = "Security group ID for ECS API tasks"
  type        = string
}

variable "sg_ecs_worker_id" {
  description = "Security group ID for ECS Worker tasks"
  type        = string
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for the ALB HTTPS listener"
  type        = string
}

variable "ecr_image_uri" {
  description = "ECR image URI (without tag)"
  type        = string
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "secrets_read_policy_arn" {
  description = "ARN of the IAM policy granting read access to Secrets Manager"
  type        = string
}

variable "db_host" {
  description = "RDS instance hostname"
  type        = string
}

variable "db_port" {
  description = "RDS instance port"
  type        = number
  default     = 5432
}

variable "db_name" {
  description = "Database name"
  type        = string
}

variable "db_username" {
  description = "Database username"
  type        = string
}

variable "redis_host" {
  description = "Redis primary endpoint hostname"
  type        = string
}

variable "db_password_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the DB password"
  type        = string
}

variable "redis_auth_token_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the Redis AUTH token"
  type        = string
}

variable "oidc_signing_key_secret_arn" {
  description = "ARN of the Secrets Manager secret containing the OIDC signing key"
  type        = string
}

variable "log_level" {
  description = "Application log level"
  type        = string
  default     = "INFO"
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days"
  type        = number
  default     = 30
}

variable "api_cpu" {
  description = "ECS API task CPU units (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "ECS API task memory in MiB"
  type        = number
  default     = 1024
}

variable "api_desired_count" {
  description = "Desired number of API tasks"
  type        = number
  default     = 2
}

variable "api_min_count" {
  description = "Minimum number of API tasks (auto-scaling floor)"
  type        = number
  default     = 1
}

variable "api_max_count" {
  description = "Maximum number of API tasks (auto-scaling ceiling)"
  type        = number
  default     = 10
}

variable "worker_cpu" {
  description = "ECS Worker task CPU units"
  type        = number
  default     = 1024
}

variable "worker_memory" {
  description = "ECS Worker task memory in MiB"
  type        = number
  default     = 2048
}

variable "worker_desired_count" {
  description = "Desired number of Worker tasks"
  type        = number
  default     = 1
}

variable "worker_min_count" {
  description = "Minimum number of Worker tasks"
  type        = number
  default     = 1
}

variable "worker_max_count" {
  description = "Maximum number of Worker tasks"
  type        = number
  default     = 20
}

variable "enable_deletion_protection" {
  description = "Enable deletion protection on the ALB"
  type        = bool
  default     = false
}

variable "alb_access_logs_bucket" {
  description = "S3 bucket name for ALB access logs (empty string to disable)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
