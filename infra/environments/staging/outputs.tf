output "alb_dns_name" {
  description = "ALB DNS name — create a CNAME record pointing to this"
  value       = var.enable_runtime ? module.ecs[0].alb_dns_name : null
}

output "db_endpoint" {
  description = "RDS endpoint"
  value       = module.rds.db_endpoint
  sensitive   = true
}

output "redis_endpoint" {
  description = "Redis primary endpoint"
  value       = module.redis.primary_endpoint
  sensitive   = true
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = var.enable_runtime ? module.ecs[0].cluster_name : null
}

output "api_service_name" {
  description = "ECS API service name for controlled promotion"
  value       = var.enable_runtime ? module.ecs[0].api_service_name : null
}

output "worker_service_name" {
  description = "ECS worker service name for controlled promotion"
  value       = var.enable_runtime ? module.ecs[0].worker_service_name : null
}

output "assurance_service_name" {
  description = "ECS assurance service name for controlled promotion"
  value       = var.enable_runtime ? module.ecs[0].assurance_service_name : null
}

output "migrator_task_definition_arn" {
  description = "Dedicated migrator task definition; run it before runtime service updates."
  value       = var.enable_runtime ? module.ecs[0].migrator_task_definition_arn : null
}

output "api_task_definition_arn" {
  description = "API task definition for controlled promotion"
  value       = var.enable_runtime ? module.ecs[0].api_task_definition_arn : null
}

output "worker_task_definition_arn" {
  description = "Worker task definition for controlled promotion"
  value       = var.enable_runtime ? module.ecs[0].worker_task_definition_arn : null
}

output "assurance_task_definition_arn" {
  description = "Assurance task definition for controlled promotion"
  value       = var.enable_runtime ? module.ecs[0].assurance_task_definition_arn : null
}

output "frontend_service_name" {
  description = "ECS customer frontend service name"
  value       = var.enable_runtime ? module.ecs[0].frontend_service_name : null
}
