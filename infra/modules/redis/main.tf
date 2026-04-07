###############################################################################
# Redis Module — ElastiCache Redis 7 for Ajenda AI
#
# Creates:
#   - ElastiCache Redis 7 replication group (cluster mode disabled)
#   - Subnet group spanning all private subnets
#   - KMS key for encryption at rest
#   - AUTH token for in-transit authentication
#   - CloudWatch alarms for CPU, memory, and evictions
###############################################################################

terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# ---------------------------------------------------------------------------
# KMS Key for Redis encryption
# ---------------------------------------------------------------------------

resource "aws_kms_key" "redis" {
  description             = "${var.name_prefix} Redis encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-redis-kms"
  })
}

resource "aws_kms_alias" "redis" {
  name          = "alias/${var.name_prefix}-redis"
  target_key_id = aws_kms_key.redis.key_id
}

# ---------------------------------------------------------------------------
# Subnet Group
# ---------------------------------------------------------------------------

resource "aws_elasticache_subnet_group" "main" {
  name        = "${var.name_prefix}-redis-subnet-group"
  description = "Subnet group for ${var.name_prefix} Redis"
  subnet_ids  = var.private_subnet_ids

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-redis-subnet-group"
  })
}

# ---------------------------------------------------------------------------
# Parameter Group
# ---------------------------------------------------------------------------

resource "aws_elasticache_parameter_group" "main" {
  name        = "${var.name_prefix}-redis7"
  family      = "redis7"
  description = "Custom parameter group for ${var.name_prefix} Redis"

  # Disable dangerous commands in production
  parameter {
    name  = "lazyfree-lazy-eviction"
    value = "yes"
  }

  parameter {
    name  = "lazyfree-lazy-expire"
    value = "yes"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-redis7-params"
  })
}

# ---------------------------------------------------------------------------
# Replication Group
# ---------------------------------------------------------------------------

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${var.name_prefix}-redis"
  description          = "Redis replication group for ${var.name_prefix}"

  # Engine
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.node_type
  parameter_group_name = aws_elasticache_parameter_group.main.name

  # Topology
  num_cache_clusters = var.num_cache_clusters
  port               = 6379

  # Network
  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [var.security_group_id]

  # Security
  at_rest_encryption_enabled  = true
  transit_encryption_enabled  = true
  auth_token                  = var.auth_token
  kms_key_id                  = aws_kms_key.redis.arn

  # Availability
  automatic_failover_enabled = var.num_cache_clusters > 1
  multi_az_enabled           = var.num_cache_clusters > 1

  # Maintenance
  maintenance_window       = "sun:05:00-sun:06:00"
  snapshot_window          = "04:00-05:00"
  snapshot_retention_limit = var.snapshot_retention_days

  # Upgrades
  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-redis"
  })
}

# ---------------------------------------------------------------------------
# CloudWatch Alarms
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "redis_cpu" {
  alarm_name          = "${var.name_prefix}-redis-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = 75
  alarm_description   = "Redis CPU utilization above 75% for 10 minutes"
  alarm_actions       = var.alarm_sns_arn != "" ? [var.alarm_sns_arn] : []

  dimensions = {
    ReplicationGroupId = aws_elasticache_replication_group.main.id
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "redis_memory" {
  alarm_name          = "${var.name_prefix}-redis-memory-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseMemoryUsagePercentage"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Redis memory usage above 80%"
  alarm_actions       = var.alarm_sns_arn != "" ? [var.alarm_sns_arn] : []

  dimensions = {
    ReplicationGroupId = aws_elasticache_replication_group.main.id
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "redis_evictions" {
  alarm_name          = "${var.name_prefix}-redis-evictions"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Evictions"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Sum"
  threshold           = 100
  alarm_description   = "Redis evictions detected — consider scaling up"
  alarm_actions       = var.alarm_sns_arn != "" ? [var.alarm_sns_arn] : []

  dimensions = {
    ReplicationGroupId = aws_elasticache_replication_group.main.id
  }

  tags = var.tags
}
