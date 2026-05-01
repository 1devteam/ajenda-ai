"""Drift guards for Docker image entrypoints and startup scripts."""

from __future__ import annotations

from pathlib import Path

API_DOCKERFILE = Path("deploy/docker/api.Dockerfile")
WORKER_DOCKERFILE = Path("deploy/docker/worker.Dockerfile")
MIGRATE_DOCKERFILE = Path("deploy/docker/migrate.Dockerfile")
START_API_SCRIPT = Path("deploy/scripts/start-api.sh")
START_WORKER_SCRIPT = Path("deploy/scripts/start-worker.sh")
RUN_MIGRATIONS_SCRIPT = Path("deploy/scripts/run-migrations.sh")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_api_image_entrypoint_uses_start_api_script() -> None:
    dockerfile = _read(API_DOCKERFILE)
    script = _read(START_API_SCRIPT)

    assert 'ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]' in dockerfile
    assert "uvicorn backend.main:app" in script
    assert '--port "${AJENDA_PORT:-8000}"' in script


def test_worker_image_entrypoint_uses_worker_loop_script() -> None:
    dockerfile = _read(WORKER_DOCKERFILE)
    script = _read(START_WORKER_SCRIPT)

    assert 'ENTRYPOINT ["/app/deploy/scripts/start-worker.sh"]' in dockerfile
    assert "settings.validate_runtime_contract()" in script
    assert "build_queue_adapter(settings)" in script
    assert "queue_adapter.ping()" in script
    assert "WorkerLoop(" in script
    assert "tenant_id=settings.worker_tenant_id" in script


def test_migrate_image_entrypoint_uses_migration_script() -> None:
    dockerfile = _read(MIGRATE_DOCKERFILE)
    script = _read(RUN_MIGRATIONS_SCRIPT)

    assert 'ENTRYPOINT ["/app/deploy/scripts/run-migrations.sh"]' in dockerfile
    assert "alembic upgrade head" in script


def test_runtime_images_copy_deploy_scripts() -> None:
    for dockerfile_path in (API_DOCKERFILE, WORKER_DOCKERFILE, MIGRATE_DOCKERFILE):
        dockerfile = _read(dockerfile_path)
        assert "COPY deploy/scripts /app/deploy/scripts" in dockerfile


def test_api_and_worker_images_include_curl_for_runtime_checks() -> None:
    assert "curl" in _read(API_DOCKERFILE)
    assert "curl" in _read(WORKER_DOCKERFILE)
