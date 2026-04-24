from pathlib import Path


def test_api_deployment_uses_mounted_probe_paths() -> None:
    content = Path("deploy/k8s/api-deployment.yaml").read_text(encoding="utf-8")

    assert "/readiness" in content
    assert "/health" in content
    assert "/system/readiness" not in content
    assert "/system/health" not in content
