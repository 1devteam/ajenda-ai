###############################################################################
# RDS Module — PostgreSQL 16 for Ajenda AI
#
# Creates:
#   - RDS PostgreSQL 16 instance (Multi-AZ in production)
#   - DB subnet group spanning all private subnets
#   - Custom parameter group with performance and security settings
#   - KMS key for encryption at rest
#   - CloudWatch alarms for CPU, storage, and connection count
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
# KMS Key for RDS encryption
# ---------------------------------------------------------------------------

resource "aws_kms_key" "rds" {
  description             = "${var.name_prefix} RDS encryption key"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-rds-kms"
  })
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${var.name_prefix}-rds"
  target_key_id = aws_kms_key.rds.key_id
}

# ---------------------------------------------------------------------------
# DB Subnet Group
# ---------------------------------------------------------------------------

resource "aws_db_subnet_group" "main" {
  name        = "${var.name_prefix}-db-subnet-group"
  description = "Subnet group for ${var.name_prefix} RDS"
  subnet_ids  = var.private_subnet_ids

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-db-subnet-group"
  })
}

# ---------------------------------------------------------------------------
# Parameter Group — PostgreSQL 16 tuning
# ---------------------------------------------------------------------------

resource "aws_db_parameter_group" "main" {
  name        = "${var.name_prefix}-pg16"
  family      = "postgres16"
  description = "Custom parameter group for ${var.name_prefix}"

  # Enable SSL — all connections must use TLS
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  # Log slow queries (> 1 second)
  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  # Log connections and disconnections for audit
  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  # Shared buffers — set to 25% of instance RAM (managed by RDS, but documented)
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-pg16-params"
  })
}

# ---------------------------------------------------------------------------
# RDS Instance
# ---------------------------------------------------------------------------

resource "aws_db_instance" "main" {
  identifier = "${var.name_prefix}-postgres"

  # Engine
  engine               = "postgres"
  engine_version       = "16"
  instance_class       = var.instance_class
  parameter_group_name = aws_db_parameter_group.main.name

  # Storage
  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.max_allocated_storage_gb
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  # Database
  db_name  = var.db_name
  username = var.db_username
  password = var.db_password  # Sourced from Secrets Manager by the caller

  # Network
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [var.security_group_id]
  publicly_accessible    = false
  port                   = 5432

  # High availability
  multi_az = var.multi_az

  # Backups
  backup_retention_period   = var.backup_retention_days
  backup_window             = "03:00-04:00"  # UTC — low traffic window
  maintenance_window        = "sun:04:00-sun:05:00"
  copy_tags_to_snapshot     = true
  delete_automated_backups  = false

  # Deletion protection — always on in production
  deletion_protection = var.deletion_protection

  # Performance Insights
  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  # Enhanced monitoring
  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.rds_monitoring.arn

  # Upgrades
  auto_minor_version_upgrade = true
  apply_immediately          = false

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-postgres"
  })

  lifecycle {
    # Prevent accidental deletion of the database
    prevent_destroy = false  # Set to true in production via tfvars
    ignore_changes  = [password]  # Password managed via Secrets Manager rotation
  }
}

# ---------------------------------------------------------------------------
# Enhanced Monitoring IAM Role
# ---------------------------------------------------------------------------

resource "aws_iam_role" "rds_monitoring" {
  name = "${var.name_prefix}-rds-monitoring-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ---------------------------------------------------------------------------
# CloudWatch Alarms
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "${var.name_prefix}-rds-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "RDS CPU utilization above 80% for 10 minutes"
  alarm_actions       = var.alarm_sns_arn != "" ? [var.alarm_sns_arn] : []

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "rds_storage" {
  alarm_name          = "${var.name_prefix}-rds-storage-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 10737418240  # 10 GB in bytes
  alarm_description   = "RDS free storage below 10 GB"
  alarm_actions       = var.alarm_sns_arn != "" ? [var.alarm_sns_arn] : []

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "rds_connections" {
  alarm_name          = "${var.name_prefix}-rds-connections-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "DatabaseConnections"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.max_connections_alarm_threshold
  alarm_description   = "RDS connection count above threshold"
  alarm_actions       = var.alarm_sns_arn != "" ? [var.alarm_sns_arn] : []

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }

  tags = var.tags
}
