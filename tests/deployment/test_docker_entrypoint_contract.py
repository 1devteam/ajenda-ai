"""Drift guards for Docker image entrypoints and startup scripts."""

from __future__ import annotations

from pathlib import Path

ROOT_DOCKERFILE = Path("Dockerfile")
API_DOCKERFILE = Path("deploy/docker/api.Dockerfile")
WORKER_DOCKERFILE = Path("deploy/docker/worker.Dockerfile")
MIGRATE_DOCKERFILE = Path("deploy/docker/migrate.Dockerfile")
FRONTEND_DOCKERFILE = Path("deploy/docker/frontend.Dockerfile")
START_API_SCRIPT = Path("deploy/scripts/start-api.sh")
START_WORKER_SCRIPT = Path("deploy/scripts/start-worker.sh")
RUN_MIGRATIONS_SCRIPT = Path("deploy/scripts/run-migrations.sh")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_root_and_deploy_api_dockerfiles_share_production_entrypoint() -> None:
    root = _read(ROOT_DOCKERFILE)
    deploy = _read(API_DOCKERFILE)

    assert 'ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]' in root
    assert 'ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]' in deploy
    assert "COPY deploy/scripts /app/deploy/scripts" in root
    assert "COPY deploy/scripts /app/deploy/scripts" in deploy


def test_api_image_entrypoint_uses_start_api_script() -> None:
    dockerfile = _read(API_DOCKERFILE)
    script = _read(START_API_SCRIPT)

    assert 'ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]' in dockerfile
    assert "uvicorn backend.main:app" in script
    assert 'port="${AJENDA_PORT:-8000}"' in script
    assert "AJENDA_UVICORN_WORKERS" in script


def test_worker_image_entrypoint_uses_worker_loop_script() -> None:
    dockerfile = _read(WORKER_DOCKERFILE)
    script = _read(START_WORKER_SCRIPT)

    assert 'ENTRYPOINT ["/app/deploy/scripts/start-worker.sh"]' in dockerfile
    assert "settings.validate_runtime_contract()" in script
    assert "build_queue_adapter(settings)" in script
    assert "queue_adapter.ping()" in script
    assert "WorkerLoop(" in script
    assert "build_claim_target(" in script
    assert "queue=queue_adapter" in script
    assert "claim_target=claim_target" in script


def test_migrate_image_entrypoint_uses_migration_script() -> None:
    dockerfile = _read(MIGRATE_DOCKERFILE)
    script = _read(RUN_MIGRATIONS_SCRIPT)

    assert 'ENTRYPOINT ["/app/deploy/scripts/run-migrations.sh"]' in dockerfile
    assert "alembic upgrade head" in script


def test_main_registers_sanitized_global_exception_handler() -> None:
    main_py = _read(Path("backend/main.py"))
    assert "unhandled_exception_handler" in main_py
    assert '"Internal server error"' in main_py


def test_runtime_images_copy_deploy_scripts() -> None:
    for dockerfile_path in (API_DOCKERFILE, WORKER_DOCKERFILE, MIGRATE_DOCKERFILE):
        dockerfile = _read(dockerfile_path)
        assert "COPY deploy/scripts /app/deploy/scripts" in dockerfile


def test_api_and_worker_images_include_curl_for_runtime_checks() -> None:
    assert "curl" in _read(API_DOCKERFILE)
    assert "curl" in _read(WORKER_DOCKERFILE)


def test_api_image_includes_autonomy_disclaimer_catalog() -> None:
    dockerfile = _read(API_DOCKERFILE)
    assert "autonomy-disclaimer-catalog.v1.yaml" in dockerfile


def test_frontend_image_builds_static_assets_with_nginx() -> None:
    dockerfile = _read(FRONTEND_DOCKERFILE)
    assert "npm run build" in dockerfile
    assert "nginx:1.27-alpine" in dockerfile
    assert "deploy/nginx/" in dockerfile
