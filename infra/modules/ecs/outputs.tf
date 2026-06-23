output "cluster_id" {
  description = "ECS cluster ID"
  value       = aws_ecs_cluster.main.id
}

output "cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "alb_dns_name" {
  description = "ALB DNS name (use this to create a CNAME record in Route 53)"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID (use with Route 53 alias records)"
  value       = aws_lb.main.zone_id
}

output "alb_arn" {
  description = "ALB ARN"
  value       = aws_lb.main.arn
}

output "api_service_name" {
  description = "ECS API service name"
  value       = aws_ecs_service.api.name
}

output "worker_service_name" {
  description = "ECS Worker service name"
  value       = aws_ecs_service.worker.name
}

output "api_task_role_arn" {
  description = "ARN of the ECS API task IAM role"
  value       = aws_iam_role.api_task.arn
}

output "worker_task_role_arn" {
  description = "ARN of the ECS Worker task IAM role"
  value       = aws_iam_role.worker_task.arn
}

output "https_listener_arn" {
  description = "ARN of the ALB HTTPS listener"
  value       = aws_lb_listener.https.arn
}

output "frontend_service_name" {
  description = "ECS frontend service name (empty when disabled)"
  value       = var.enable_customer_frontend ? aws_ecs_service.frontend[0].name : ""
}

output "frontend_target_group_arn" {
  description = "ALB target group ARN for the customer frontend (empty when disabled)"
  value       = var.enable_customer_frontend ? aws_lb_target_group.frontend[0].arn : ""
}
