from pathlib import Path

API_DEPLOYMENT = Path("deploy/k8s/api-deployment.yaml")
HEALTHCHECK_SCRIPT = Path("deploy/scripts/healthcheck.sh")
READINESSCHECK_SCRIPT = Path("deploy/scripts/readinesscheck.sh")

EXPECTED_HEALTH_PATH = "/health"
EXPECTED_READINESS_PATH = "/readiness"
EXPECTED_PROBE_PORT = "8000"


def test_api_deployment_uses_mounted_probe_paths() -> None:
    content = API_DEPLOYMENT.read_text(encoding="utf-8")

    assert EXPECTED_READINESS_PATH in content
    assert EXPECTED_HEALTH_PATH in content
    assert "/system/readiness" not in content
    assert "/system/health" not in content


def test_k8s_api_probe_paths_match_probe_scripts() -> None:
    api_deployment = API_DEPLOYMENT.read_text(encoding="utf-8")
    healthcheck = HEALTHCHECK_SCRIPT.read_text(encoding="utf-8")
    readinesscheck = READINESSCHECK_SCRIPT.read_text(encoding="utf-8")

    assert f"path: {EXPECTED_HEALTH_PATH}" in api_deployment
    assert f"path: {EXPECTED_READINESS_PATH}" in api_deployment
    assert EXPECTED_HEALTH_PATH in healthcheck
    assert EXPECTED_READINESS_PATH in readinesscheck


def test_k8s_api_probes_use_application_port() -> None:
    api_deployment = API_DEPLOYMENT.read_text(encoding="utf-8")
    healthcheck = HEALTHCHECK_SCRIPT.read_text(encoding="utf-8")
    readinesscheck = READINESSCHECK_SCRIPT.read_text(encoding="utf-8")

    assert f"port: {EXPECTED_PROBE_PORT}" in api_deployment
    assert f"${{AJENDA_PORT:-{EXPECTED_PROBE_PORT}}}" in healthcheck
    assert f"${{AJENDA_PORT:-{EXPECTED_PROBE_PORT}}}" in readinesscheck
