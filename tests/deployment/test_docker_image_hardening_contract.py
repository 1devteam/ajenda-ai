"""Drift guards for production image hardening and build-context hygiene."""

from __future__ import annotations

from pathlib import Path

DOCKERIGNORE = Path(".dockerignore")
ROOT_DOCKERFILE = Path("Dockerfile")
API_DOCKERFILE = Path("deploy/docker/api.Dockerfile")
WORKER_DOCKERFILE = Path("deploy/docker/worker.Dockerfile")
MIGRATE_DOCKERFILE = Path("deploy/docker/migrate.Dockerfile")
FRONTEND_DOCKERFILE = Path("deploy/docker/frontend.Dockerfile")
HUBSPOT_DOCKERFILE = Path("services/hubspot_crm_adapter/Dockerfile")

PYTHON_RUNTIME_DOCKERFILES = (
    ROOT_DOCKERFILE,
    API_DOCKERFILE,
    WORKER_DOCKERFILE,
    MIGRATE_DOCKERFILE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dockerignore_excludes_secrets_caches_and_local_tooling() -> None:
    text = _read(DOCKERIGNORE)

    for marker in (
        ".git",
        ".env",
        "frontend/node_modules",
        "tests/",
        "**/__pycache__",
        "frontend/.env",
        "**/*.pem",
    ):
        assert marker in text


def test_python_runtime_images_run_as_non_root_uid_1000() -> None:
    for path in PYTHON_RUNTIME_DOCKERFILES:
        text = _read(path)
        assert "USER 1000" in text, f"{path} must drop privileges to uid 1000"
        assert "useradd --uid 1000" in text, f"{path} must create the non-root runtime user"
        assert "AS builder" in text, f"{path} must use a multi-stage build"


def test_python_runtime_images_do_not_ship_build_toolchains() -> None:
    for path in PYTHON_RUNTIME_DOCKERFILES:
        # Final stage is the last python:3.12-slim FROM (builder uses "AS builder").
        runtime_stage = _read(path).rsplit("FROM python:3.12-slim", 1)[-1]
        assert "build-essential" not in runtime_stage, f"{path} runtime stage must not install build-essential"
        assert "libpq5" in runtime_stage, f"{path} runtime stage must include libpq5"


def test_api_images_include_autonomy_catalog_and_match_hardening() -> None:
    root = _read(ROOT_DOCKERFILE)
    api = _read(API_DOCKERFILE)

    for text in (root, api):
        assert "autonomy-disclaimer-catalog.v1.yaml" in text
        assert 'ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]' in text
        assert "USER 1000" in text
        assert "AS builder" in text


def test_frontend_image_does_not_declare_credential_shaped_env_keys() -> None:
    text = _read(FRONTEND_DOCKERFILE)

    assert "VITE_API_BASE_URL=" in text
    assert "VITE_DEFAULT_API_KEY" not in text
    assert "VITE_DEFAULT_TENANT_ID" not in text
    assert "rm -f .env" in text


def test_hubspot_adapter_image_runs_as_non_root() -> None:
    text = _read(HUBSPOT_DOCKERFILE)

    assert "USER 1000" in text
    assert "useradd --uid 1000" in text
