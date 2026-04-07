variable "name_prefix" {
  description = "Prefix for all resource names"
  type        = string
}

variable "private_subnet_ids" {
  description = "IDs of the private subnets for the Redis subnet group"
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group ID to attach to the Redis replication group"
  type        = string
}

variable "node_type" {
  description = "ElastiCache node type (e.g. cache.t4g.small for staging, cache.r7g.large for production)"
  type        = string
  default     = "cache.t4g.small"
}

variable "num_cache_clusters" {
  description = "Number of cache clusters (1 for staging, 2+ for production with failover)"
  type        = number
  default     = 1
}

variable "auth_token" {
  description = "AUTH token for Redis in-transit authentication — sourced from Secrets Manager"
  type        = string
  sensitive   = true
}

variable "snapshot_retention_days" {
  description = "Number of days to retain Redis snapshots"
  type        = number
  default     = 3
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
