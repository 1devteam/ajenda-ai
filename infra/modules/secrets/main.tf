###############################################################################
# Existing-secret access policy
#
# Secret material is created, rotated, and owned outside Terraform. This module
# accepts only ARNs and grants the ECS execution role permission to inject them.
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

data "aws_iam_policy_document" "ecs_secrets_read" {
  for_each = var.secret_arns_by_runtime
  statement {
    sid       = "ReadAjendaRuntimeSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = tolist(each.value)
  }
}

resource "aws_iam_policy" "ecs_secrets_read" {
  for_each = var.secret_arns_by_runtime
  name     = "${var.name_prefix}-${each.key}-ecs-secrets-read"
  policy   = data.aws_iam_policy_document.ecs_secrets_read[each.key].json
  tags     = var.tags
}
