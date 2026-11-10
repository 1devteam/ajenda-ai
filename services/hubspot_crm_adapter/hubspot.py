from __future__ import annotations

from typing import Any

import httpx

HUBSPOT_API_BASE = "https://api.hubapi.com"

RECORD_TYPE_TO_OBJECT: dict[str, str] = {
    "contact": "contacts",
    "company": "companies",
    "deal": "deals",
}

CONTACT_IDENTITY_PROPERTIES = ("email",)
COMPANY_IDENTITY_PROPERTIES = ("domain", "name")
DEAL_IDENTITY_PROPERTIES = ("dealname",)

PROVIDER_PROPERTY_ALLOWLIST: dict[str, frozenset[str]] = {
    "contacts": frozenset({"email", "firstname", "lastname", "phone", "company", "website", "jobtitle"}),
    "companies": frozenset({"name", "domain", "website", "phone", "description"}),
    "deals": frozenset({"dealname", "amount", "dealstage", "closedate", "pipeline"}),
}


class HubSpotApiError(Exception):
    def __init__(self, *, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class HubSpotClient:
    def __init__(
        self,
        *,
        access_token: str,
        api_base: str = HUBSPOT_API_BASE,
        timeout_seconds: float = 15.0,
    ) -> None:
        token = access_token.strip()
        if not token:
            raise ValueError("HubSpot access token is required")
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout_seconds
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def search(
        self,
        *,
        company: str | None,
        domain: str | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        if domain and domain.strip():
            return self._search_object(
                object_type="companies",
                filters=[
                    {
                        "propertyName": "domain",
                        "operator": "EQ",
                        "value": domain.strip(),
                    }
                ],
            )
        if company and company.strip():
            object_type, results = self._search_object(
                object_type="companies",
                filters=[
                    {
                        "propertyName": "name",
                        "operator": "CONTAINS_TOKEN",
                        "value": company.strip(),
                    }
                ],
            )
            # HubSpot company search does not include contact properties. Read
            # the tenant's matching contacts through the provider API as
            # separate observed records so downstream qualification/enrichment
            # can consume real CRM relationships without inventing contacts.
            for result in results:
                properties = result.get("properties") if isinstance(result.get("properties"), dict) else {}
                company_name = str(properties.get("name") or company).strip()
                if not company_name:
                    continue
                try:
                    _, contacts = self._search_object(
                        object_type="contacts",
                        filters=[
                            {
                                "propertyName": "company",
                                "operator": "CONTAINS_TOKEN",
                                "value": company_name,
                            }
                        ],
                    )
                except HubSpotApiError:
                    # The company observation remains valid when the token lacks
                    # contact-search scope; the missing relationship is retained
                    # as an evidence gap for the downstream observer.
                    contacts = []
                result["contacts"] = contacts
            return object_type, results
        return "companies", []

    def upsert(self, *, record_type: str, data: dict[str, Any]) -> dict[str, Any]:
        normalized_type = record_type.strip().lower()
        object_type = RECORD_TYPE_TO_OBJECT.get(normalized_type)
        if object_type is None:
            raise ValueError(f"unsupported record_type: {record_type}")

        # A lead is an Ajenda qualification signal, not a person.  Never turn
        # an unresolved lead into a HubSpot contact merely because an external
        # CRM upsert was requested.
        if normalized_type == "lead":
            raise ValueError("HubSpot upsert does not accept lead records; resolve a verified contact first")

        allowed = PROVIDER_PROPERTY_ALLOWLIST.get(object_type, frozenset())
        supplied = {str(key) for key, value in data.items() if value is not None and str(key) != "provider_record_id"}
        unsupported = sorted(supplied - allowed)
        if unsupported:
            raise ValueError("unsupported HubSpot properties: " + ", ".join(unsupported))
        properties = {
            str(key): self._normalize_property_value(object_type=object_type, property_name=str(key), value=value)
            for key, value in data.items()
            if value is not None and str(key) in allowed
        }
        if not properties:
            raise ValueError("data must include at least one property")

        provider_record_id = data.get("provider_record_id")
        if provider_record_id is not None and (
            not isinstance(provider_record_id, str) or not provider_record_id.strip()
        ):
            raise ValueError("provider_record_id must be a non-empty HubSpot object id when provided")
        if object_type == "companies" and provider_record_id is None and not properties.get("domain"):
            raise ValueError(
                "HubSpot company creation/update requires domain or provider_record_id; name is not an identity"
            )
        if object_type == "deals" and provider_record_id is None:
            raise ValueError("HubSpot deal update requires provider_record_id; deal names are not identities")
        existing_id = (
            provider_record_id.strip()
            if isinstance(provider_record_id, str)
            else self._find_existing_id(object_type=object_type, properties=properties)
        )
        if existing_id:
            updated = self._patch_object(object_type=object_type, object_id=existing_id, properties=properties)
            return {
                "record_type": normalized_type,
                "hubspot_object_type": object_type,
                "id": existing_id,
                "created": False,
                "requested_properties": properties,
                "properties": updated.get("properties", properties),
            }

        created = self._create_object(object_type=object_type, properties=properties)
        created_id = str(created.get("id", ""))
        if not created_id:
            raise HubSpotApiError(status_code=502, detail="HubSpot create response missing id")
        return {
            "record_type": normalized_type,
            "hubspot_object_type": object_type,
            "id": created_id,
            "created": True,
            "requested_properties": properties,
            "properties": created.get("properties", properties),
        }

    def read(self, *, record_type: str, record_id: str) -> dict[str, Any]:
        """Read one provider object after a mutation for effect verification."""

        normalized_type = record_type.strip().lower()
        object_type = RECORD_TYPE_TO_OBJECT.get(normalized_type)
        if object_type is None:
            raise ValueError(f"unsupported record_type: {record_type}")
        normalized_id = record_id.strip()
        if not normalized_id:
            raise ValueError("record_id is required")
        payload = self._request(
            method="GET",
            path=f"/crm/v3/objects/{object_type}/{normalized_id}?properties={','.join(self._default_properties(object_type))}",
        )
        if not isinstance(payload, dict):
            raise HubSpotApiError(status_code=502, detail="unexpected HubSpot read response")
        return payload

    def _search_object(
        self,
        *,
        object_type: str,
        filters: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        payload: dict[str, Any] = {
            "filterGroups": [{"filters": filters}],
            "limit": 25,
            "properties": self._default_properties(object_type),
        }
        normalized: list[dict[str, Any]] = []
        # HubSpot returns paging cursors. Bounded pagination makes an
        # ambiguity visible instead of silently selecting an arbitrary record.
        # Search consumers receive at most 100 records, sufficient to detect
        # conflicts without creating unbounded provider reads.
        for _ in range(4):
            response = self._request(
                method="POST",
                path=f"/crm/v3/objects/{object_type}/search",
                json_body=payload,
            )
            results = response.get("results", []) if isinstance(response, dict) else []
            if not isinstance(results, list):
                break
            normalized.extend(item for item in results if isinstance(item, dict))
            paging = response.get("paging") if isinstance(response, dict) else None
            next_page = paging.get("next") if isinstance(paging, dict) else None
            after = next_page.get("after") if isinstance(next_page, dict) else None
            if not isinstance(after, str) or not after.strip():
                break
            payload["after"] = after.strip()
        return object_type, normalized

    def _find_existing_id(self, *, object_type: str, properties: dict[str, str]) -> str | None:
        filters = self._identity_filters(object_type=object_type, properties=properties)
        if not filters:
            return None
        _, results = self._search_object(object_type=object_type, filters=filters)
        if not results:
            return None
        if len(results) != 1:
            raise HubSpotApiError(
                status_code=409,
                detail=f"HubSpot identity lookup is ambiguous for {object_type}; provide provider_record_id",
            )
        object_id = results[0].get("id")
        return str(object_id) if object_id is not None else None

    def _identity_filters(self, *, object_type: str, properties: dict[str, str]) -> list[dict[str, Any]]:
        if object_type == "contacts":
            email = properties.get("email")
            if email:
                return [{"propertyName": "email", "operator": "EQ", "value": email}]
            return []
        if object_type == "companies":
            domain = properties.get("domain")
            if domain:
                return [{"propertyName": "domain", "operator": "EQ", "value": domain}]
            return []
        if object_type == "deals":
            # Deal names are not identities. This adapter changes deals only
            # through an explicit provider record id.
            return []
        return []

    @staticmethod
    def _normalize_property_value(*, object_type: str, property_name: str, value: Any) -> str:
        """Validate HubSpot's string wire format without silently coercing objects."""
        if isinstance(value, bool):
            raise ValueError(f"HubSpot property {property_name} must not be boolean")
        if isinstance(value, (str, int, float)):
            return str(value)
        raise ValueError(
            f"HubSpot property {property_name} for {object_type} must be a string or number, not {type(value).__name__}"
        )

    def _create_object(self, *, object_type: str, properties: dict[str, str]) -> dict[str, Any]:
        response = self._request(
            method="POST",
            path=f"/crm/v3/objects/{object_type}",
            json_body={"properties": properties},
        )
        if not isinstance(response, dict):
            raise HubSpotApiError(status_code=502, detail="unexpected HubSpot create response")
        return response

    def _patch_object(self, *, object_type: str, object_id: str, properties: dict[str, str]) -> dict[str, Any]:
        response = self._request(
            method="PATCH",
            path=f"/crm/v3/objects/{object_type}/{object_id}",
            json_body={"properties": properties},
        )
        if not isinstance(response, dict):
            raise HubSpotApiError(status_code=502, detail="unexpected HubSpot update response")
        return response

    def _default_properties(self, object_type: str) -> list[str]:
        if object_type == "contacts":
            return ["email", "firstname", "lastname", "company", "phone"]
        if object_type == "companies":
            return ["name", "domain", "website", "phone", "description"]
        if object_type == "deals":
            return ["dealname", "amount", "dealstage", "pipeline"]
        return []

    def _request(self, *, method: str, path: str, json_body: dict[str, Any] | None = None) -> Any:
        url = f"{self._api_base}{path}"
        try:
            with httpx.Client(timeout=self._timeout, follow_redirects=False) as client:
                response = client.request(method, url, headers=self._headers, json=json_body)
        except httpx.TimeoutException as exc:
            raise HubSpotApiError(status_code=504, detail="HubSpot API request timed out") from exc
        except httpx.HTTPError as exc:
            raise HubSpotApiError(status_code=502, detail="HubSpot API request failed") from exc

        if response.status_code >= 400:
            detail = response.text[:500] if response.text else f"HubSpot API returned HTTP {response.status_code}"
            raise HubSpotApiError(status_code=response.status_code, detail=detail)

        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise HubSpotApiError(status_code=502, detail="HubSpot API returned non-JSON response") from exc


def bearer_token_from_header(authorization: str | None) -> str:
    if not authorization or not authorization.strip():
        raise ValueError("Authorization header is required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ValueError("Authorization must be a Bearer token")
    return token.strip()
