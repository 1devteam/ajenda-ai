from pathlib import Path


REQUIRED_TERMS = (
    "tenant-governed autonomous execution",
    "TenantLifecycleService",
    "QuotaEnforcementService",
    "TenantPlan",
    "TenantUsage",
    "QUOTA_EXCEEDED",
    "docs/SAAS_ARCHITECTURE.md",
)


def test_saas_architecture_doc_exists_and_defines_foundation() -> None:
    text = Path("docs/SAAS_ARCHITECTURE.md").read_text()

    for term in REQUIRED_TERMS[:-1]:
        assert term in text


def test_readme_links_saas_architecture_doc() -> None:
    readme = Path("README.md").read_text()

    assert REQUIRED_TERMS[-1] in readme
