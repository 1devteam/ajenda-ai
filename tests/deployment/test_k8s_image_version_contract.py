"""Drift guards for Kubernetes image tags and deployment version labels."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PYPROJECT = Path("pyproject.toml")
API_DEPLOYMENT = Path("deploy/k8s/api-deployment.yaml")
WORKER_DEPLOYMENT = Path("deploy/k8s/worker-deployment.yaml")

EXPECTED_API_IMAGE_REPOSITORY = "ajenda/api"
EXPECTED_WORKER_IMAGE_REPOSITORY = "ajenda/worker"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _project_version() -> str:
    with PYPROJECT.open("rb") as pyproject:
        data = tomllib.load(pyproject)
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


def _manifest_image(manifest: str) -> str:
    match = re.search(r"^\s*image:\s*(?P<image>\S+)\s*$", manifest, flags=re.MULTILINE)
    assert match is not None, "deployment manifest must define a container image"
    return match.group("image")


def test_api_deployment_image_tag_matches_project_version() -> None:
    version = _project_version()
    image = _manifest_image(_read(API_DEPLOYMENT))

    assert image == f"{EXPECTED_API_IMAGE_REPOSITORY}:{version}"


def test_worker_deployment_image_tag_matches_project_version() -> None:
    version = _project_version()
    image = _manifest_image(_read(WORKER_DEPLOYMENT))

    assert image == f"{EXPECTED_WORKER_IMAGE_REPOSITORY}:{version}"


def test_k8s_deployment_manifests_do_not_use_latest_tags() -> None:
    for manifest_path in (API_DEPLOYMENT, WORKER_DEPLOYMENT):
        image = _manifest_image(_read(manifest_path))

        assert not image.endswith(":latest"), f"{manifest_path} must not use mutable :latest image tags"


def test_api_deployment_version_labels_match_project_version() -> None:
    version = _project_version()
    manifest = _read(API_DEPLOYMENT)

    assert f'version: "{version}"' in manifest


def test_worker_deployment_version_label_matches_project_version() -> None:
    version = _project_version()
    manifest = _read(WORKER_DEPLOYMENT)

    assert f'version: "{version}"' in manifest
