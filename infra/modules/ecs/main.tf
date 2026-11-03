###############################################################################
# ECS module — Ajenda's controlled runtime target
#
# Terraform creates immutable task-definition revisions and service plumbing.
# It deliberately does not promote those revisions, apply migrations, or create
# database roles.  `deploy/scripts/ecs-promote.sh` owns that ordered operation.
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

locals {
  common_environment = [
    for name, value in var.runtime_environment : {
      name  = name
      value = value
    }
  ]
  common_secrets = [
    for name, arn in var.runtime_secret_arns : {
      name      = name
      valueFrom = arn
    }
  ]
}

resource "aws_ecs_cluster" "main" {
  name = "${var.name_prefix}-cluster"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = merge(var.tags, { Name = "${var.name_prefix}-cluster" })
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = "FARGATE"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.name_prefix}/api"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.name_prefix}/worker"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "assurance" {
  name              = "/ecs/${var.name_prefix}/assurance"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "migrator" {
  name              = "/ecs/${var.name_prefix}/migrator"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_iam_role" "ecs_execution" {
  for_each = toset(["api", "worker", "assurance", "migrator", "frontend"])
  name     = "${var.name_prefix}-${each.key}-ecs-execution-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
  tags = var.tags
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  for_each   = aws_iam_role.ecs_execution
  role       = each.value.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy_attachment" "ecs_execution_secrets" {
  for_each   = var.secrets_read_policy_arns
  role       = aws_iam_role.ecs_execution[each.key].name
  policy_arn = each.value
}

resource "aws_iam_role" "api_task" {
  name               = "${var.name_prefix}-api-task-role"
  assume_role_policy = aws_iam_role.ecs_execution["api"].assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role" "worker_task" {
  name               = "${var.name_prefix}-worker-task-role"
  assume_role_policy = aws_iam_role.ecs_execution["worker"].assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role" "assurance_task" {
  name               = "${var.name_prefix}-assurance-task-role"
  assume_role_policy = aws_iam_role.ecs_execution["assurance"].assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role" "migrator_task" {
  name               = "${var.name_prefix}-migrator-task-role"
  assume_role_policy = aws_iam_role.ecs_execution["migrator"].assume_role_policy
  tags               = var.tags
}

resource "aws_iam_role" "frontend_task" {
  name               = "${var.name_prefix}-frontend-task-role"
  assume_role_policy = aws_iam_role.ecs_execution["frontend"].assume_role_policy
  tags               = var.tags
}

resource "aws_lb" "main" {
  name                       = "${var.name_prefix}-alb"
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [var.sg_alb_id]
  subnets                    = var.public_subnet_ids
  enable_deletion_protection = var.enable_deletion_protection
  drop_invalid_header_fields = true
  access_logs {
    bucket  = var.alb_access_logs_bucket
    prefix  = "${var.name_prefix}-alb"
    enabled = var.alb_access_logs_bucket != ""
  }
  tags = merge(var.tags, { Name = "${var.name_prefix}-alb" })
}

resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.acm_certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = var.enable_customer_frontend && length(aws_lb_target_group.frontend) > 0 ? aws_lb_target_group.frontend[0].arn : aws_lb_target_group.api.arn
  }
}

resource "aws_lb_target_group" "api" {
  name        = "${var.name_prefix}-api-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    enabled             = true
    path                = "/health"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }
  tags = merge(var.tags, { Name = "${var.name_prefix}-api-tg" })
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.ecs_execution["api"].arn
  task_role_arn            = aws_iam_role.api_task.arn
  container_definitions = jsonencode([{
    name         = "api"
    image        = var.api_image
    essential    = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = concat(local.common_environment, [{ name = "AJENDA_DATABASE_IDENTITY", value = "api" }])
    secrets      = concat([{ name = "AJENDA_DATABASE_URL", valueFrom = var.api_database_url_secret_arn }], local.common_secrets)
    logConfiguration = { logDriver = "awslogs", options = {
      "awslogs-group" = aws_cloudwatch_log_group.api.name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "api"
    } }
    healthCheck = { command = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"], interval = 30, timeout = 5, retries = 3, startPeriod = 60 }
  }])
  tags = merge(var.tags, { Name = "${var.name_prefix}-api-task" })
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = aws_iam_role.ecs_execution["worker"].arn
  task_role_arn            = aws_iam_role.worker_task.arn
  container_definitions = jsonencode([{
    name        = "worker"
    image       = var.worker_image
    essential   = true
    environment = concat(local.common_environment, [{ name = "AJENDA_DATABASE_IDENTITY", value = "worker" }])
    secrets     = concat([{ name = "AJENDA_DATABASE_URL", valueFrom = var.worker_database_url_secret_arn }], local.common_secrets)
    logConfiguration = { logDriver = "awslogs", options = {
      "awslogs-group" = aws_cloudwatch_log_group.worker.name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "worker"
    } }
  }])
  tags = merge(var.tags, { Name = "${var.name_prefix}-worker-task" })
}

resource "aws_ecs_task_definition" "assurance" {
  family                   = "${var.name_prefix}-assurance"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.assurance_cpu
  memory                   = var.assurance_memory
  execution_role_arn       = aws_iam_role.ecs_execution["assurance"].arn
  task_role_arn            = aws_iam_role.assurance_task.arn
  container_definitions = jsonencode([{
    name       = "assurance"
    image      = var.assurance_image
    essential  = true
    entryPoint = ["sh", "/app/deploy/scripts/start-assurance.sh"]
    environment = concat(local.common_environment, [
      { name = "AJENDA_DATABASE_IDENTITY", value = "assurance" },
      { name = "AJENDA_ASSURANCE_INTERVAL_SECONDS", value = tostring(var.assurance_interval_seconds) },
    ])
    secrets = [{ name = "AJENDA_DATABASE_URL", valueFrom = var.assurance_database_url_secret_arn }]
    logConfiguration = { logDriver = "awslogs", options = {
      "awslogs-group" = aws_cloudwatch_log_group.assurance.name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "assurance"
    } }
  }])
  tags = merge(var.tags, { Name = "${var.name_prefix}-assurance-task" })
}

resource "aws_ecs_task_definition" "migrator" {
  family                   = "${var.name_prefix}-migrator"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.migrator_cpu
  memory                   = var.migrator_memory
  execution_role_arn       = aws_iam_role.ecs_execution["migrator"].arn
  task_role_arn            = aws_iam_role.migrator_task.arn
  container_definitions = jsonencode([{
    name        = "migrator"
    image       = var.migrator_image
    essential   = true
    environment = concat(local.common_environment, [{ name = "AJENDA_DATABASE_IDENTITY", value = "migrator" }])
    secrets     = [{ name = "AJENDA_DATABASE_URL", valueFrom = var.migrator_database_url_secret_arn }]
    logConfiguration = { logDriver = "awslogs", options = {
      "awslogs-group" = aws_cloudwatch_log_group.migrator.name, "awslogs-region" = var.aws_region, "awslogs-stream-prefix" = "migrator"
    } }
  }])
  tags = merge(var.tags, { Name = "${var.name_prefix}-migrator-task" })
}

resource "aws_ecs_service" "api" {
  name            = "${var.name_prefix}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  # Terraform creates services dormant. The controlled promotion procedure is
  # the only owner allowed to start them after a successful migrator task.
  desired_count   = 0
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.sg_ecs_api_id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  deployment_controller { type = "ECS" }
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 60
  tags                               = merge(var.tags, { Name = "${var.name_prefix}-api-service" })
  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }
  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "worker" {
  name            = "${var.name_prefix}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 0
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.sg_ecs_worker_id]
    assign_public_ip = false
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  tags                               = merge(var.tags, { Name = "${var.name_prefix}-worker-service" })
  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }
}

resource "aws_ecs_service" "assurance" {
  name            = "${var.name_prefix}-assurance"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.assurance.arn
  desired_count   = 0
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.sg_ecs_worker_id]
    assign_public_ip = false
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  tags                               = merge(var.tags, { Name = "${var.name_prefix}-assurance-service" })
  lifecycle {
    ignore_changes = [desired_count, task_definition]
  }
}

resource "aws_appautoscaling_target" "api" {
  max_capacity       = var.api_max_count
  # Promotion raises this from zero only after the migrator succeeded.
  min_capacity       = 0
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "api_cpu" {
  name               = "${var.name_prefix}-api-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
    target_value       = 70
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_target" "worker" {
  max_capacity       = var.worker_max_count
  # Promotion raises this from zero only after the migrator succeeded.
  min_capacity       = 0
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "worker_cpu" {
  name               = "${var.name_prefix}-worker-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.worker.service_namespace
  target_tracking_scaling_policy_configuration {
    predefined_metric_specification { predefined_metric_type = "ECSServiceAverageCPUUtilization" }
    target_value       = 75
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
