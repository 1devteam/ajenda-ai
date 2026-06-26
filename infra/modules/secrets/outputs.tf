output "db_password_secret_arn" {
  value = aws_secretsmanager_secret.db_password.arn
}

output "redis_auth_token_secret_arn" {
  value = aws_secretsmanager_secret.redis_auth_token.arn
}

output "oidc_signing_key_secret_arn" {
  value = aws_secretsmanager_secret.oidc_signing_key.arn
}

output "webhook_hmac_master_key_secret_arn" {
  value = aws_secretsmanager_secret.webhook_hmac_master_key.arn
}

output "ecs_secrets_read_policy_arn" {
  value = aws_iam_policy.ecs_secrets_read.arn
}