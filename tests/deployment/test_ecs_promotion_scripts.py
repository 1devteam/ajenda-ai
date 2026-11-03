"""Behavioral contract tests for the explicit ECS operator procedures.

These tests use a local fake AWS CLI.  They prove the scripts' ordering and
fail-closed behavior; they are not evidence of an AWS deployment.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMOTION = REPO_ROOT / "deploy/scripts/ecs-promote.sh"
ROLLBACK = REPO_ROOT / "deploy/scripts/ecs-rollback.sh"


def _write_fake_commands(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "commands.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "aws").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >> "${AJENDA_TEST_COMMAND_LOG}"\n'
        "if [[ \"$*\" == *'ecs run-task'* ]]; then echo 'arn:task/migrator'; fi\n"
        'if [[ "$*" == *\'ecs describe-tasks\'* ]]; then echo "${AJENDA_TEST_MIGRATOR_EXIT_CODE:-0}"; fi\n',
        encoding="utf-8",
    )
    (fake_bin / "curl").write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\nprintf \'curl %s\\n\' "$*" >> "${AJENDA_TEST_COMMAND_LOG}"\n',
        encoding="utf-8",
    )
    for command in fake_bin.iterdir():
        command.chmod(0o755)
    return fake_bin, log


def _environment(fake_bin: Path, log: Path, **overrides: str) -> dict[str, str]:
    environment = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "AJENDA_TEST_COMMAND_LOG": str(log),
        "AJENDA_ECS_CLUSTER": "ajenda-staging",
        "AJENDA_ECS_SUBNETS": "subnet-a,subnet-b",
        "AJENDA_ECS_SECURITY_GROUPS": "sg-runtime",
        "AJENDA_ECS_MIGRATOR_TASK_DEFINITION": "ajenda-migrator:12",
        "AJENDA_ECS_API_SERVICE": "ajenda-api",
        "AJENDA_ECS_API_TASK_DEFINITION": "ajenda-api:12",
        "AJENDA_ECS_API_DESIRED_COUNT": "2",
        "AJENDA_ECS_API_MIN_COUNT": "2",
        "AJENDA_ECS_API_MAX_COUNT": "10",
        "AJENDA_ECS_WORKER_SERVICE": "ajenda-worker",
        "AJENDA_ECS_WORKER_TASK_DEFINITION": "ajenda-worker:12",
        "AJENDA_ECS_WORKER_DESIRED_COUNT": "1",
        "AJENDA_ECS_WORKER_MIN_COUNT": "1",
        "AJENDA_ECS_WORKER_MAX_COUNT": "20",
        "AJENDA_ECS_ASSURANCE_SERVICE": "ajenda-assurance",
        "AJENDA_ECS_ASSURANCE_TASK_DEFINITION": "ajenda-assurance:12",
        "AJENDA_ECS_ASSURANCE_DESIRED_COUNT": "1",
        "AJENDA_ECS_API_BASE_URL": "https://api.example.test",
        **overrides,
    }
    return environment


def _run(script: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(script)], cwd=REPO_ROOT, env=environment, text=True, capture_output=True, check=False)


def test_promotion_runs_the_migrator_before_any_service_update(tmp_path: Path) -> None:
    fake_bin, log = _write_fake_commands(tmp_path)
    result = _run(PROMOTION, _environment(fake_bin, log, AJENDA_ECS_PROMOTION_APPROVED="1"))

    assert result.returncode == 0, result.stderr
    commands = log.read_text(encoding="utf-8").splitlines()
    assert commands[:3] == [
        "ecs run-task --cluster ajenda-staging --launch-type FARGATE --task-definition ajenda-migrator:12 --network-configuration awsvpcConfiguration={subnets=[subnet-a,subnet-b],securityGroups=[sg-runtime],assignPublicIp=DISABLED} --started-by "
        + commands[0].split(" --started-by ", 1)[1],
        "ecs wait tasks-stopped --cluster ajenda-staging --tasks arn:task/migrator",
        "ecs describe-tasks --cluster ajenda-staging --tasks arn:task/migrator --query tasks[0].containers[0].exitCode --output text",
    ]
    first_update = next(index for index, command in enumerate(commands) if command.startswith("ecs update-service"))
    assert first_update > 2
    assert [command for command in commands if command.startswith("ecs update-service")] == [
        "ecs update-service --cluster ajenda-staging --service ajenda-api --task-definition ajenda-api:12 --desired-count 2 --force-new-deployment --no-cli-pager",
        "ecs update-service --cluster ajenda-staging --service ajenda-worker --task-definition ajenda-worker:12 --desired-count 1 --force-new-deployment --no-cli-pager",
        "ecs update-service --cluster ajenda-staging --service ajenda-assurance --task-definition ajenda-assurance:12 --desired-count 1 --force-new-deployment --no-cli-pager",
    ]
    assert [
        command for command in commands if command.startswith("application-autoscaling register-scalable-target")
    ] == [
        "application-autoscaling register-scalable-target --service-namespace ecs --resource-id service/ajenda-staging/ajenda-api --scalable-dimension ecs:service:DesiredCount --min-capacity 2 --max-capacity 10 --no-cli-pager",
        "application-autoscaling register-scalable-target --service-namespace ecs --resource-id service/ajenda-staging/ajenda-worker --scalable-dimension ecs:service:DesiredCount --min-capacity 1 --max-capacity 20 --no-cli-pager",
    ]
    assert commands[-1].startswith("curl --fail --silent --show-error --max-time 20 https://api.example.test/readiness")


def test_failed_migrator_prevents_service_promotion(tmp_path: Path) -> None:
    fake_bin, log = _write_fake_commands(tmp_path)
    result = _run(
        PROMOTION,
        _environment(
            fake_bin,
            log,
            AJENDA_ECS_PROMOTION_APPROVED="1",
            AJENDA_TEST_MIGRATOR_EXIT_CODE="1",
        ),
    )

    assert result.returncode != 0
    assert "migrator task failed" in result.stderr
    assert not any(command.startswith("ecs update-service") for command in log.read_text(encoding="utf-8").splitlines())


def test_invalid_capacity_range_prevents_any_aws_call(tmp_path: Path) -> None:
    fake_bin, log = _write_fake_commands(tmp_path)
    result = _run(
        PROMOTION,
        _environment(
            fake_bin,
            log,
            AJENDA_ECS_PROMOTION_APPROVED="1",
            AJENDA_ECS_API_MIN_COUNT="3",
            AJENDA_ECS_API_DESIRED_COUNT="2",
        ),
    )

    assert result.returncode != 0
    assert "api requires minimum <= desired <= maximum" in result.stderr
    assert not log.exists()


def test_rollback_requires_explicit_schema_compatibility_approval(tmp_path: Path) -> None:
    fake_bin, log = _write_fake_commands(tmp_path)
    result = _run(ROLLBACK, _environment(fake_bin, log))

    assert result.returncode != 0
    assert "AJENDA_ECS_SCHEMA_COMPATIBILITY_APPROVED must be set" in result.stderr
    assert not log.exists()


def test_approved_rollback_updates_only_services_and_checks_readiness(tmp_path: Path) -> None:
    fake_bin, log = _write_fake_commands(tmp_path)
    result = _run(ROLLBACK, _environment(fake_bin, log, AJENDA_ECS_SCHEMA_COMPATIBILITY_APPROVED="1"))

    assert result.returncode == 0, result.stderr
    commands = log.read_text(encoding="utf-8").splitlines()
    assert all("run-task" not in command for command in commands)
    assert [command for command in commands if command.startswith("ecs update-service")] == [
        "ecs update-service --cluster ajenda-staging --service ajenda-api --task-definition ajenda-api:12 --force-new-deployment --no-cli-pager",
        "ecs update-service --cluster ajenda-staging --service ajenda-worker --task-definition ajenda-worker:12 --force-new-deployment --no-cli-pager",
        "ecs update-service --cluster ajenda-staging --service ajenda-assurance --task-definition ajenda-assurance:12 --force-new-deployment --no-cli-pager",
    ]
    assert commands[-1].startswith("curl --fail --silent --show-error --max-time 20 https://api.example.test/readiness")
