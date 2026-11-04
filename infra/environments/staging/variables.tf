variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "enable_runtime" {
  description = "Create ECS runtime resources only after secret references and image digests are approved."
  type        = bool
  default     = false
}
variable "acm_certificate_arn" { default = "" }
variable "api_image" { default = "" }
variable "worker_image" { default = "" }
variable "assurance_image" { default = "" }
variable "migrator_image" { default = "" }
variable "frontend_image" { default = "" }
variable "api_database_url_secret_arn" { default = "" }
variable "worker_database_url_secret_arn" { default = "" }
variable "assurance_database_url_secret_arn" { default = "" }
variable "migrator_database_url_secret_arn" { default = "" }
variable "runtime_secret_arns" { default = {} }
variable "runtime_environment" {
  type = map(string)
  default = {
    AJENDA_ENV                           = "staging"
    AJENDA_LOG_LEVEL                     = "INFO"
    AJENDA_QUEUE_ADAPTER                 = "redis"
    AJENDA_WORKER_TENANT_MODE            = "multi"
    AJENDA_WORKER_TENANT_REFRESH_SECONDS = "30"
  }
}
