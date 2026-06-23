"""Drift guards for Terraform customer frontend module wiring."""

from __future__ import annotations

from pathlib import Path

FRONTEND_TF = Path("infra/modules/ecs/frontend.tf")
VPC_MAIN = Path("infra/modules/vpc/main.tf")
SECRETS_MAIN = Path("infra/modules/secrets/main.tf")
STAGING_MAIN = Path("infra/environments/staging/main.tf")
PRODUCTION_MAIN = Path("infra/environments/production/main.tf")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ecs_module_declares_frontend_path_routing() -> None:
    content = _read(FRONTEND_TF)
    assert "aws_lb_target_group" in content and "frontend" in content
    assert 'values = ["/v1/*"]' in content
    assert 'values = ["/health"]' in content
    assert 'values = ["/readiness"]' in content


def test_vpc_module_exposes_frontend_security_group() -> None:
    vpc = _read(VPC_MAIN)
    assert "aws_security_group" in vpc and "ecs_frontend" in vpc
    assert "sg_ecs_frontend_id" in _read(Path("infra/modules/vpc/outputs.tf"))


def test_secrets_module_exists_for_environment_roots() -> None:
    secrets = _read(SECRETS_MAIN)
    assert "aws_secretsmanager_secret" in secrets
    assert "ecs_secrets_read_policy_arn" in _read(Path("infra/modules/secrets/outputs.tf"))


def test_environment_roots_wire_customer_frontend() -> None:
    staging = _read(STAGING_MAIN)
    production = _read(PRODUCTION_MAIN)
    for content in (staging, production):
        assert "sg_ecs_frontend_id" in content
        assert "ecr_frontend_image_uri" in content
        assert "enable_customer_frontend = true" in content
