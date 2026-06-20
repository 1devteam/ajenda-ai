from pathlib import Path


def test_dev_compose_matches_prod_runtime_slice() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    for service in ("api", "worker", "migrate", "db", "redis"):
        assert f"{service}:" in compose

    assert "dockerfile: Dockerfile" in compose or "dockerfile: deploy/docker/api.Dockerfile" in compose
    assert "deploy/docker/worker.Dockerfile" in compose
    assert "deploy/docker/migrate.Dockerfile" in compose
    assert 'ENTRYPOINT ["/app/deploy/scripts/start-api.sh"]' in Path("Dockerfile").read_text(encoding="utf-8")
