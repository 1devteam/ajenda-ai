from __future__ import annotations

import pytest

from backend.app.config import Settings


def test_production_api_identity_requires_api_database_role() -> None:
    settings = Settings.model_construct(
        env="production",
        database_identity="api",
        database_url="postgresql+psycopg://ajenda_api:password@db:5432/ajenda",
    )

    settings.validate_database_identity(expected_identity="api")


def test_production_api_identity_rejects_bootstrap_or_migrator_connection() -> None:
    settings = Settings.model_construct(
        env="production",
        database_identity="api",
        database_url="postgresql+psycopg://ajenda_migrator:password@db:5432/ajenda",
    )

    with pytest.raises(ValueError, match="must connect as 'ajenda_api'"):
        settings.validate_database_identity(expected_identity="api")


def test_production_rejects_unclassified_database_identity() -> None:
    settings = Settings.model_construct(
        env="production",
        database_identity="development",
        database_url="postgresql+psycopg://ajenda_api:password@db:5432/ajenda",
    )

    with pytest.raises(ValueError, match="least-privilege process identity"):
        settings.validate_database_identity(expected_identity="api")


def test_production_rejects_vector_connection_with_another_role() -> None:
    settings = Settings.model_construct(
        env="production",
        database_identity="api",
        database_url="postgresql+psycopg://ajenda_api:password@db:5432/ajenda",
        vector_database_url="postgresql+psycopg://ajenda_migrator:password@vector-db:5432/ajenda_vector",
        vector_db_enabled=True,
    )

    with pytest.raises(ValueError, match="must connect as 'ajenda_api'"):
        settings.validate_database_identity(expected_identity="api")
