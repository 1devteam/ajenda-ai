from pathlib import Path


def test_required_k8s_manifests_exist() -> None:
    required = [
        "deploy/k8s/api-deployment.yaml",
        "deploy/k8s/worker-deployment.yaml",
        "deploy/k8s/migrate-job.yaml",
        "deploy/k8s/api-service.yaml",
        "deploy/k8s/ingress.yaml",
    ]
    for path in required:
        assert Path(path).exists(), path
