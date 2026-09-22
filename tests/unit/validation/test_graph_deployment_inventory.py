from pathlib import Path

from scripts.validation.graph_deployment_inventory import collect_deployment_inventory


def test_browser_deployment_inventory_exposes_dependency_image_and_startup_edges() -> None:
    inventory = collect_deployment_inventory(Path(__file__).parents[3])

    node_ids = {node["id"] for node in inventory["nodes"]}
    edge_pairs = {(edge["from"], edge["to"], edge["type"]) for edge in inventory["edges"]}

    assert "dependency:playwright" in node_ids
    assert "runtime-binary:chromium" in node_ids
    assert (
        "action:web.browser_session",
        "dependency:playwright",
        "requires_runtime_dependency",
    ) in edge_pairs
    assert (
        "runtime-binary:chromium",
        "deployment-browser:worker-image",
        "installed_in",
    ) in edge_pairs
    assert inventory["findings"] == []
    assert inventory["metrics"]["deployment_unknown_count"] == 1
    assert inventory["unknowns"][0]["id"] == "deployment-browser:flag-value-externalized"


def test_browser_deployment_inventory_fails_closed_when_support_is_missing(tmp_path: Path) -> None:
    for relative in (
        "pyproject.toml",
        "deploy/docker/worker.Dockerfile",
        "deploy/scripts/start-worker.sh",
        "backend/app/config.py",
        "backend/services/internet/browser_session.py",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")

    inventory = collect_deployment_inventory(tmp_path)

    assert {item["classification"] for item in inventory["findings"]} == {"deployment_support_gap"}
    assert inventory["metrics"]["deployment_finding_count"] == 5
