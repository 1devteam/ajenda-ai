"""Kernel Compose must boot without HubSpot.

Slice 0 of docs/planning/CORE_INDEPENDENCE_AND_ENTERPRISE_PLAN.md:
api and worker must not depends_on hubspot-crm-ingress. HubSpot services stay
behind Compose profile `hubspot`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "deploy" / "compose" / "docker-compose.prod.yml",
)


def _service_block(text: str, service: str) -> str:
    pattern = rf"(?m)^  {re.escape(service)}:\n(?P<body>(?:^    .*\n|^$)*)"
    match = re.search(pattern, text)
    assert match is not None, f"service {service!r} not found"
    return match.group("body")


def _depends_on_block(service_body: str) -> str:
    match = re.search(r"(?m)^    depends_on:\n(?P<body>(?:^      .*\n)*)", service_body)
    if match is None:
        return ""
    return match.group("body")


def test_kernel_services_do_not_depend_on_hubspot() -> None:
    for path in COMPOSE_FILES:
        text = path.read_text(encoding="utf-8")
        for service in ("api", "worker"):
            depends = _depends_on_block(_service_block(text, service))
            assert "hubspot" not in depends.lower(), (
                f"{path} service {service} still depends on HubSpot:\n{depends}"
            )


def test_hubspot_services_are_profiled_optional() -> None:
    for path in COMPOSE_FILES:
        text = path.read_text(encoding="utf-8")
        for service in ("hubspot-crm-adapter", "hubspot-crm-ingress"):
            body = _service_block(text, service)
            assert re.search(r"(?m)^    profiles:\n(?:      - hubspot\n)+", body) or (
                'profiles: ["hubspot"]' in body
            ), f"{path} service {service} must use profiles: [hubspot]\n{body}"


def test_live_runtime_proof_does_not_require_hubspot_certs() -> None:
    script = (REPO_ROOT / "deploy" / "scripts" / "live-runtime-proof.sh").read_text(encoding="utf-8")
    assert "AJENDA_PROOF_START_HUBSPOT_INGRESS" in script
    assert "fail \"HubSpot ingress cert script not found" in script
    # Default kernel start list must not include hubspot services.
    start_line = next(line for line in script.splitlines() if "compose up -d --build" in line)
    assert "hubspot" not in start_line.lower()
    assert "api" in start_line and "worker" in start_line
