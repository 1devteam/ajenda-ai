###############################################################################
# Secrets Module — AWS Secrets Manager + ECS read policy
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

resource "aws_secretsmanager_secret" "db_password" {
  name = "${var.name_prefix}/db-password"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = var.db_password
}

resource "aws_secretsmanager_secret" "redis_auth_token" {
  name = "${var.name_prefix}/redis-auth-token"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "redis_auth_token" {
  secret_id     = aws_secretsmanager_secret.redis_auth_token.id
  secret_string = var.redis_auth_token
}

resource "aws_secretsmanager_secret" "oidc_signing_key" {
  name = "${var.name_prefix}/oidc-signing-key"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "oidc_signing_key" {
  secret_id     = aws_secretsmanager_secret.oidc_signing_key.id
  secret_string = var.oidc_signing_key_pem
}

resource "aws_secretsmanager_secret" "webhook_hmac_master_key" {
  name = "${var.name_prefix}/webhook-hmac-master-key"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "webhook_hmac_master_key" {
  secret_id     = aws_secretsmanager_secret.webhook_hmac_master_key.id
  secret_string = var.webhook_hmac_master_key
}

data "aws_iam_policy_document" "ecs_secrets_read" {
  statement {
    sid    = "ReadAjendaSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]
    resources = [
      aws_secretsmanager_secret.db_password.arn,
      aws_secretsmanager_secret.redis_auth_token.arn,
      aws_secretsmanager_secret.oidc_signing_key.arn,
      aws_secretsmanager_secret.webhook_hmac_master_key.arn,
    ]
  }
}

resource "aws_iam_policy" "ecs_secrets_read" {
  name   = "${var.name_prefix}-ecs-secrets-read"
  policy = data.aws_iam_policy_document.ecs_secrets_read.json
  tags   = var.tags
}