from pathlib import Path


def test_dev_compose_matches_prod_runtime_slice() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for service in ("frontend", "api", "worker", "migrate", "db", "redis"):
        assert f"{service}:" in compose

    assert "dockerfile: Dockerfile" in compose or "dockerfile: deploy/docker/api.Dockerfile" in compose
    assert "deploy/docker/worker.Dockerfile" in compose
    assert "deploy/docker/migrate.Dockerfile" in compose
    assert 'ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]' in Path("Dockerfile").read_text(encoding="utf-8")


def test_dev_compose_forces_shared_queue_and_multi_tenant_worker() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert compose.count("AJENDA_QUEUE_ADAPTER: redis") == 2
    assert compose.count("AJENDA_QUEUE_URL: redis://redis:6379/0") == 2
    assert "AJENDA_WORKER_TENANT_MODE: multi" in compose
    assert 'AJENDA_WORKER_TENANT_REFRESH_SECONDS: "30"' in compose
    assert "AJENDA_WORKER_TENANT_ID:" not in compose


def test_dev_compose_frontend_waits_for_healthy_api() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'test: ["CMD-SHELL", "/app/deploy/scripts/readinesscheck.sh"]' in compose
    assert "condition: service_healthy" in compose
