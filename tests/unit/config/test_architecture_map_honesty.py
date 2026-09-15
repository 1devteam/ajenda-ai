"""Slice 3: architecture maps match the kernel after slices 0-2.

Docs are not runtime proof. These tests only stop the maps from claiming
August 2026 HubSpot/GTM/vertical boot as current truth.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHITECTURE = REPO_ROOT / "docs" / "architecture" / "SYSTEM_ARCHITECTURE.md"
CRM_MAP = REPO_ROOT / "docs" / "architecture" / "INTERNAL_CRM_COMPLETION_MAP.md"
GRAFT_MAP = REPO_ROOT / "docs" / "planning" / "GRAFT1ST_UNIVERSAL_CRM_CANONICAL_MAP.md"
DOCS_INDEX = REPO_ROOT / "docs" / "README.md"
PROD_ENV = REPO_ROOT / "docs" / "deployment" / "production-env-contract.md"
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "deploy" / "compose" / "docker-compose.prod.yml",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _mermaid_blocks(text: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", text, flags=re.DOTALL)


def test_architecture_head_is_alembic_0045() -> None:
    text = _read(ARCHITECTURE)
    assert "**Head revision:** `0045_stripe_revenue_payload`" in text
    assert "**Head revision:** `0038_knowledge_retrieval`" not in text


def test_architecture_kernel_inventory_and_records() -> None:
    text = _read(ARCHITECTURE)
    for service in ("api", "worker", "frontend", "migrate", "db", "redis"):
        assert service in text
    assert "/v1/crm` is Ajenda Records" in text
    assert "Ajenda Records" in text
    assert "AJENDA_VERTICAL_OPS_ENABLED" in text
    assert "compose --profile hubspot" in text


def test_architecture_mermaid_does_not_put_hubspot_on_default_path() -> None:
    for block in _mermaid_blocks(_read(ARCHITECTURE)):
        assert "hubspot" not in block.lower()


def test_internal_crm_map_remaining_p1_is_duplicate_merge() -> None:
    text = _read(CRM_MAP)
    assert "HubSpot is not a completion item" in text
    assert "reviewed duplicate merge" in text or "reviewed merge" in text


def test_graft_universal_crm_map_is_superseded() -> None:
    text = _read(GRAFT_MAP)
    assert text.lower().startswith("# g.r.a.f.t.1st") or "**Status:** superseded" in text
    assert "superseded" in text.lower()
    assert "Missions consume Ajenda Records" in text


def test_docs_index_aligned_to_slice_3() -> None:
    text = _read(DOCS_INDEX)
    assert "2026-09-15" in text
    assert "2026-07-07 until Slice 3" not in text


def test_production_env_contract_hubspot_optional() -> None:
    text = _read(PROD_ENV)
    assert "AJENDA_HUBSPOT_CRM_ADAPTER_PUBLIC_HOST" in text
    assert "empty adapter host is legal" in text.lower() or "Empty default" in text
    assert "not required to boot" in text.lower()


def test_compose_api_worker_still_have_no_hubspot_depends_on() -> None:
    for path in COMPOSE_FILES:
        text = path.read_text(encoding="utf-8")
        for service in ("api", "worker"):
            match = re.search(rf"(?m)^  {re.escape(service)}:\n(?P<body>(?:^    .*\n|^$)*)", text)
            assert match is not None, f"{path} missing {service}"
            depends = re.search(r"(?m)^    depends_on:\n(?P<body>(?:^      .*\n)*)", match.group("body"))
            block = depends.group("body") if depends else ""
            assert "hubspot" not in block.lower(), f"{path} {service} depends_on HubSpot:\n{block}"
