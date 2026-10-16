from backend.services.runtime_information_observation import describe_information, safe_decision_keys


def test_description_reveals_structure_not_values_or_sensitive_field_names() -> None:
    value = {
        "target_market": "Phoenix HVAC",
        "password": "secret-password",
        "authorization_header": "Bearer token",
        "results": [{"company": "Private Business"}],
    }
    observed = describe_information(value)
    assert observed["shape"] == "object"
    assert observed["item_count"] == 4
    assert observed["field_names"] == ["results", "target_market"]
    rendered = str(observed)
    for secret in ("Phoenix HVAC", "secret-password", "Bearer token", "Private Business"):
        assert secret not in rendered


def test_representation_fingerprint_does_not_change_with_private_values() -> None:
    first = describe_information({"target_market": "Phoenix", "password": "one"})
    second = describe_information({"target_market": "Dallas", "password": "two"})
    assert first["sha256"] == second["sha256"]


def test_technical_decision_keys_redact_arbitrary_text() -> None:
    assert safe_decision_keys(
        ["research_prospects", "Send password abc to partner", "target_entities[0].industry"],
        limit=3,
    ) == ["research_prospects", "[redacted]", "target_entities[0].industry"]


def test_free_form_dictionary_keys_are_not_copied_into_audit_observation() -> None:
    description = describe_information({
        "person@example.com": "private value",
        "results": [],
        "Bearer token secret": "sensitive",
    })
    assert description["field_names"] == ["results"]
    assert "person@example.com" not in str(description)
    assert "Bearer token secret" not in str(description)


def test_nested_schema_observes_field_transformations_without_values() -> None:
    first = describe_information({
        "input": {"criteria": [{"industry": "HVAC", "city": "Phoenix"}]}
    })
    second = describe_information({
        "input": {"criteria": [{"industry": "plumbing", "city": "Dallas"}]}
    })
    assert first["structural_paths"] == second["structural_paths"]
    assert first["sha256"] == second["sha256"]
    paths = {item["path"] for item in first["structural_paths"]}
    assert "input.criteria[].industry" in paths
    assert "input.criteria[].city" in paths
    assert "Phoenix" not in str(first)
    assert "HVAC" not in str(first)


def test_nested_schema_is_bounded_and_sensitive_keys_are_excluded() -> None:
    described = describe_information({"credential": {"password": "private"}, "records": [{"name": "A"}]})
    paths = {item["path"] for item in described["structural_paths"]}
    assert "credential" not in paths
    assert "credential.password" not in paths
    assert "records[].name" in paths
