output "alb_dns_name" {
  description = "ALB DNS name — create a CNAME or Route 53 alias record pointing to this"
  value       = module.ecs.alb_dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID for Route 53 alias records"
  value       = module.ecs.alb_zone_id
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

output "api_service_name" {
  description = "ECS API service name"
  value       = module.ecs.api_service_name
}

output "worker_service_name" {
  description = "ECS Worker service name"
  value       = module.ecs.worker_service_name
}
