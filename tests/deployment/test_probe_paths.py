from pathlib import Path


def test_api_deployment_uses_system_probe_paths() -> None:
    content = Path("deploy/k8s/api-deployment.yaml").read_text(encoding="utf-8")
    assert "/system/readiness" in content
    assert "/system/health" in content
