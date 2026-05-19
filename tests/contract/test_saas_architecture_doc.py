REQUIRED_TERMS = (
    "tenant-governed autonomous execution",
    "TenantLifecycleService",
    "QuotaEnforcementService",
    "TenantPlan",
    "TenantUsage",
    "QUOTA_EXCEEDED",
    "docs/SAAS_ARCHITECTURE.md",
)


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as file:
        return file.read()


def test_saas_architecture_doc_exists_and_defines_foundation() -> None:
    text = _read_text("docs/SAAS_ARCHITECTURE.md")

    for term in REQUIRED_TERMS[:-1]:
        assert term in text


def test_readme_links_saas_architecture_doc() -> None:
    readme = _read_text("README.md")

    assert REQUIRED_TERMS[-1] in readme
