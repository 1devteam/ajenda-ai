from __future__ import annotations

from pathlib import Path

K8S_MANIFEST_DIR = Path("deploy/k8s")

EXPECTED_K8S_MANIFESTS = frozenset(
    {
        "api-deployment.yaml",
        "api-service.yaml",
        "configmap.yaml",
        "hpa-worker.yaml",
        "ingress.yaml",
        "migrate-job.yaml",
        "namespace.yaml",
        "otel-collector-config.yaml",
        "pdb.yaml",
        "prometheus-servicemonitor.yaml",
        "secret.example.yaml",
        "worker-deployment.yaml",
    }
)


def _k8s_manifest_paths() -> list[Path]:
    return sorted(path for path in K8S_MANIFEST_DIR.iterdir() if path.suffix in {".yaml", ".yml"})


def test_required_k8s_manifests_exist() -> None:
    actual = {path.name for path in _k8s_manifest_paths()}

    missing = EXPECTED_K8S_MANIFESTS - actual

    assert not missing, f"Missing required Kubernetes manifests: {sorted(missing)}"


def test_no_untracked_k8s_manifest_files_exist() -> None:
    actual = {path.name for path in _k8s_manifest_paths()}

    unexpected = actual - EXPECTED_K8S_MANIFESTS

    assert not unexpected, f"Unexpected Kubernetes manifests need inventory review: {sorted(unexpected)}"


def test_k8s_manifests_have_required_yaml_document_headers() -> None:
    for manifest_path in _k8s_manifest_paths():
        content = manifest_path.read_text(encoding="utf-8")

        assert "apiVersion:" in content, f"{manifest_path} must declare apiVersion"
        assert "kind:" in content, f"{manifest_path} must declare kind"


def test_k8s_manifest_indentation_uses_spaces_only() -> None:
    for manifest_path in _k8s_manifest_paths():
        lines = manifest_path.read_text(encoding="utf-8").splitlines()

        tabbed_lines = [line_number for line_number, line in enumerate(lines, start=1) if "\t" in line]

        assert not tabbed_lines, f"{manifest_path} contains tab indentation on lines: {tabbed_lines}"
