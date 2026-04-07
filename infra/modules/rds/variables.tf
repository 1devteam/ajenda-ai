variable "name_prefix" {
  description = "Prefix for all resource names"
  type        = string
}

variable "private_subnet_ids" {
  description = "IDs of the private subnets for the DB subnet group"
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group ID to attach to the RDS instance"
  type        = string
}

variable "instance_class" {
  description = "RDS instance class (e.g. db.t4g.medium for staging, db.r8g.large for production)"
  type        = string
  default     = "db.t4g.medium"
}

variable "allocated_storage_gb" {
  description = "Initial allocated storage in GB"
  type        = number
  default     = 20
}

variable "max_allocated_storage_gb" {
  description = "Maximum storage autoscaling ceiling in GB"
  type        = number
  default     = 100
}

variable "db_name" {
  description = "Name of the initial database"
  type        = string
  default     = "ajenda"
}

variable "db_username" {
  description = "Master username for the RDS instance"
  type        = string
  default     = "ajenda_admin"
}

variable "db_password" {
  description = "Master password — sourced from Secrets Manager by the caller"
  type        = string
  sensitive   = true
}

variable "multi_az" {
  description = "Enable Multi-AZ deployment (true for production)"
  type        = bool
  default     = false
}

variable "backup_retention_days" {
  description = "Number of days to retain automated backups"
  type        = number
  default     = 7
}

variable "deletion_protection" {
  description = "Enable deletion protection (true for production)"
  type        = bool
  default     = false
}

variable "max_connections_alarm_threshold" {
  description = "CloudWatch alarm threshold for database connection count"
  type        = number
  default     = 100
}

variable "alarm_sns_arn" {
  description = "SNS topic ARN for CloudWatch alarms (empty string to disable)"
  type        = string
  default     = ""
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
