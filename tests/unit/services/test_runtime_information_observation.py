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
