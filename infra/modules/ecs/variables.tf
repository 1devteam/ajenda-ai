variable "name_prefix" { type = string }
variable "environment" { type = string }
variable "aws_region" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }
variable "sg_alb_id" { type = string }
variable "sg_ecs_api_id" { type = string }
variable "sg_ecs_worker_id" { type = string }
variable "sg_ecs_frontend_id" { type = string }
variable "acm_certificate_arn" { type = string }
variable "secrets_read_policy_arns" {
  description = "Runtime-specific ECS execution-role policies for Secrets Manager injection."
  type        = map(string)
  validation {
    condition = length(keys(var.secrets_read_policy_arns)) == 4 && alltrue([
      for runtime in ["api", "worker", "assurance", "migrator"] : contains(keys(var.secrets_read_policy_arns), runtime)
    ])
    error_message = "secrets_read_policy_arns must contain exactly api, worker, assurance, and migrator entries."
  }
}
variable "api_database_url_secret_arn" { type = string }
variable "worker_database_url_secret_arn" { type = string }
variable "assurance_database_url_secret_arn" { type = string }
variable "migrator_database_url_secret_arn" { type = string }

variable "runtime_environment" {
  description = "Non-secret canonical AJENDA_* runtime configuration."
  type        = map(string)
  validation {
    condition     = alltrue([for required in ["AJENDA_ENV", "AJENDA_LOG_LEVEL", "AJENDA_QUEUE_ADAPTER", "AJENDA_WORKER_TENANT_MODE"] : contains(keys(var.runtime_environment), required)])
    error_message = "runtime_environment must include the canonical environment, logging, queue, and worker-tenant settings."
  }
  validation {
    condition     = !contains(keys(var.runtime_environment), "AJENDA_DATABASE_URL") && !contains(keys(var.runtime_environment), "AJENDA_DATABASE_IDENTITY")
    error_message = "Database URLs and role identities are task-specific and may not be supplied through runtime_environment."
  }
}

variable "runtime_secret_arns" {
  description = "Canonical runtime secret-name to Secrets Manager ARN map; values never enter Terraform state."
  type        = map(string)
  validation {
    condition     = alltrue([for required in ["AJENDA_QUEUE_URL", "AJENDA_RUNTIME_SECRET_ENCRYPTION_KEY", "AJENDA_WEBHOOK_SECRET_ENCRYPTION_KEY"] : contains(keys(var.runtime_secret_arns), required)])
    error_message = "runtime_secret_arns must include the queue URL and both required encryption keys."
  }
  validation {
    condition     = !contains(keys(var.runtime_secret_arns), "AJENDA_DATABASE_URL")
    error_message = "Database URL secrets are role-specific inputs."
  }
}

variable "api_image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "api_image must be an immutable OCI digest reference."
  }
}
variable "worker_image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.worker_image))
    error_message = "worker_image must be an immutable OCI digest reference."
  }
}
variable "assurance_image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.assurance_image))
    error_message = "assurance_image must be an immutable OCI digest reference."
  }
}
variable "migrator_image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.migrator_image))
    error_message = "migrator_image must be an immutable OCI digest reference."
  }
}
variable "frontend_image" {
  type = string
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.frontend_image))
    error_message = "frontend_image must be an immutable OCI digest reference."
  }
}

variable "api_cpu" { type = number }
variable "api_memory" { type = number }
variable "api_max_count" { type = number }
variable "worker_cpu" { type = number }
variable "worker_memory" { type = number }
variable "worker_max_count" { type = number }
variable "assurance_cpu" { type = number }
variable "assurance_memory" { type = number }
variable "assurance_interval_seconds" {
  type    = number
  default = 300
}
variable "migrator_cpu" {
  type    = number
  default = 512
}
variable "migrator_memory" {
  type    = number
  default = 1024
}
variable "frontend_cpu" { type = number }
variable "frontend_memory" { type = number }
variable "enable_customer_frontend" {
  type    = bool
  default = true
}
variable "enable_deletion_protection" {
  type    = bool
  default = false
}
variable "alb_access_logs_bucket" {
  type    = string
  default = ""
}
variable "log_retention_days" { type = number }
variable "tags" { type = map(string) }
