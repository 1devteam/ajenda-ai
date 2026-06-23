output "alb_dns_name" {
  description = "ALB DNS name — create a CNAME record pointing to this"
  value       = module.ecs.alb_dns_name
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
  value       = module.ecs.cluster_name
}

output "frontend_service_name" {
  description = "ECS customer frontend service name"
  value       = module.ecs.frontend_service_name
}
