output "ecs_secrets_read_policy_arns" {
  description = "IAM policy ARNs keyed by runtime; each permits only that runtime's secret ARNs."
  value       = { for runtime, policy in aws_iam_policy.ecs_secrets_read : runtime => policy.arn }
}
