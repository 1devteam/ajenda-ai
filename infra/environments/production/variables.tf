variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "db_password" {
  description = "RDS master password"
  type        = string
  sensitive   = true
}

variable "redis_auth_token" {
  description = "Redis AUTH token (minimum 16 characters)"
  type        = string
  sensitive   = true
}

variable "oidc_signing_key_pem" {
  description = "OIDC JWT signing private key in PEM format"
  type        = string
  sensitive   = true
}

variable "webhook_hmac_master_key" {
  description = "Webhook HMAC master key (minimum 32 characters)"
  type        = string
  sensitive   = true
}

variable "acm_certificate_arn" {
  description = "ARN of the ACM certificate for the ALB HTTPS listener"
  type        = string
}

variable "ecr_image_uri" {
  description = "ECR image URI without tag"
  type        = string
}

variable "image_tag" {
  description = "Docker image tag to deploy"
  type        = string
}

variable "ecr_frontend_image_uri" {
  description = "Customer frontend image URI without tag (GHCR or ECR)"
  type        = string
}

variable "frontend_image_tag" {
  description = "Customer frontend image tag"
  type        = string
  default     = "latest"
}

variable "alarm_sns_arn" {
  description = "SNS topic ARN for CloudWatch alarms"
  type        = string
  default     = ""
}

variable "alb_access_logs_bucket" {
  description = "S3 bucket name for ALB access logs"
  type        = string
  default     = ""
}
