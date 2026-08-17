from backend.services.tools.contact_observation import extract_observed_contacts, prospect_source_url


def test_extracts_mailto_and_tel() -> None:
    html = 'Call <a href="tel:4796444246">(479) 644-4246</a> or <a href="mailto:hello@nwarestoreit.com">email</a>'
    found = extract_observed_contacts(text=html, source_url="https://www.nwarestoreit.com/hazmat-service")
    values = {(item["kind"], item["value"]) for item in found}
    assert ("email", "hello@nwarestoreit.com") in values
    assert ("phone", "(479) 644-4246") in values
    assert all(item["real"] is True for item in found)


def test_drops_noreply_and_placeholder_domains() -> None:
    text = "noreply@nwarestoreit.com privacy@example.com hello@schema.org"
    found = extract_observed_contacts(text=text, source_url="https://www.nwarestoreit.com/")
    assert found == []


def test_prospect_url_from_http_field() -> None:
    assert prospect_source_url({"url": "https://biooneinc.com/bigred-ar/"}) == "https://biooneinc.com/bigred-ar/"
