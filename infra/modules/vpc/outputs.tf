output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = aws_subnet.private[*].id
}

output "sg_alb_id" {
  description = "Security group ID for the Application Load Balancer"
  value       = aws_security_group.alb.id
}

output "sg_ecs_api_id" {
  description = "Security group ID for ECS API tasks"
  value       = aws_security_group.ecs_api.id
}

output "sg_ecs_worker_id" {
  description = "Security group ID for ECS Worker tasks"
  value       = aws_security_group.ecs_worker.id
}

output "sg_rds_id" {
  description = "Security group ID for RDS"
  value       = aws_security_group.rds.id
}

output "sg_redis_id" {
  description = "Security group ID for ElastiCache Redis"
  value       = aws_security_group.redis.id
}
