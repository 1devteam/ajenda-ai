"""Calendar, LinkedIn, GitHub, and generic provider-read action input builders."""

from __future__ import annotations

from typing import Any

from backend.services.mission_composition.action_input_common import (
    _calendar_window_from_objective,
    _prospect_count,
    extract_github_owner_repo,
)
from backend.services.mission_composition.contracts import MissionIntent


def build_provider_read_action_input(*, action_name: str, intent: MissionIntent) -> dict[str, Any] | None:
    limit = _prospect_count(intent)
    if action_name == "google_calendar.events_read":
        start, end = _calendar_window_from_objective(
            intent.raw_instruction or intent.normalized_instruction or intent.objective
        )
        payload: dict[str, Any] = {"calendar_id": "primary", "limit": max(limit, 20)}
        if start:
            payload["start"] = start
        if end:
            payload["end"] = end
        return payload
    if action_name == "calendar.read":
        start, end = _calendar_window_from_objective(intent.objective)
        payload = {"limit": max(limit, 20)}
        if start:
            payload["start"] = start
        if end:
            payload["end"] = end
        return payload
    if action_name == "linkedin.profile_read":
        # Optional profile_id from target entity attributes or name; default = authenticated user.
        profile_id = None
        for entity in intent.target_entities:
            attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
            if attrs.get("linkedin_profile_id"):
                profile_id = str(attrs["linkedin_profile_id"])
                break
            if entity.type in {"person", "linkedin_profile"} and entity.name:
                profile_id = entity.name
                break
        payload = {
            "fields": ("id", "firstName", "lastName", "headline"),
        }
        if profile_id:
            payload["profile_id"] = profile_id
        return payload
    if action_name == "github.repo_read":
        parsed = extract_github_owner_repo(intent)
        if parsed is None:
            raise ValueError(
                "github.repo_read requires owner and repository (for example octocat/Hello-World); "
                "refusing to invent a placeholder repository"
            )
        owner, repo = parsed
        return {"owner": owner, "repo": repo}
    if action_name == "provider.external_read":
        # Contacts-shaped default when composition selected this action for ops.google_contacts_read.
        # Generic external read still accepts an explicit URL via target entity attributes.
        explicit_url = None
        for entity in intent.target_entities:
            if entity.url:
                explicit_url = entity.url
                break
            attrs = entity.attributes if isinstance(entity.attributes, dict) else {}
            if attrs.get("provider_read_url"):
                explicit_url = str(attrs["provider_read_url"])
                break
        if explicit_url:
            return {
                "method": "GET",
                "url": explicit_url,
                "timeout_seconds": 5.0,
                "allowed_hosts": [],
            }
        # Default: Google People API connections list (read-only contacts surface).
        return {
            "method": "GET",
            "url": (
                "https://people.googleapis.com/v1/people/me/connections"
                "?personFields=names,emailAddresses,phoneNumbers&pageSize=25"
            ),
            "timeout_seconds": 5.0,
            "allowed_hosts": ["people.googleapis.com"],
        }

    return None
