###############################################################################
# Customer frontend — ECS Fargate + ALB path routing
#
# Mirrors deploy/k8s/ingress.yaml and Compose nginx:
#   /v1/*, /health, /readiness → API
#   default /*                 → frontend SPA
###############################################################################

resource "aws_cloudwatch_log_group" "frontend" {
  count             = var.enable_customer_frontend ? 1 : 0
  name              = "/ecs/${var.name_prefix}/frontend"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lb_target_group" "frontend" {
  count       = var.enable_customer_frontend ? 1 : 0
  name        = "${var.name_prefix}-frontend-tg"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    path                = "/"
    port                = "traffic-port"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-frontend-tg"
  })
}

resource "aws_ecs_task_definition" "frontend" {
  count                    = var.enable_customer_frontend ? 1 : 0
  family                   = "${var.name_prefix}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = aws_iam_role.api_task.arn

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = "${var.ecr_frontend_image_uri}:${var.frontend_image_tag}"
      essential = true
      portMappings = [
        {
          containerPort = 80
          protocol      = "tcp"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.frontend[0].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "frontend"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1/ || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-frontend-task"
  })
}

resource "aws_ecs_service" "frontend" {
  count           = var.enable_customer_frontend ? 1 : 0
  name            = "${var.name_prefix}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend[0].arn
  desired_count   = var.frontend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.sg_ecs_frontend_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend[0].arn
    container_name   = "frontend"
    container_port   = 80
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 30

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-frontend-service"
  })

  depends_on = [aws_lb_listener.https]
}

resource "aws_lb_listener_rule" "api_v1" {
  count        = var.enable_customer_frontend ? 1 : 0
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/v1/*"]
    }
  }
}

resource "aws_lb_listener_rule" "api_health" {
  count        = var.enable_customer_frontend ? 1 : 0
  listener_arn = aws_lb_listener.https.arn
  priority     = 11

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/health"]
    }
  }
}

resource "aws_lb_listener_rule" "api_readiness" {
  count        = var.enable_customer_frontend ? 1 : 0
  listener_arn = aws_lb_listener.https.arn
  priority     = 12

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = ["/readiness"]
    }
  }
}