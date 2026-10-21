"""Explicit persisted-charter setup for integration runtime proofs.

Integration tests must not inherit editor defaults at execution time.  This
helper writes a real active-profile charter before a test exercises a runtime
path that requires tenant authority.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.repositories.business_profile_repository import BusinessProfileRepository
from backend.services.operating_charter import OperatingCharter, default_operating_charter, inspect_operating_charter


def persist_test_operating_charter(
    session: Session,
    *,
    tenant_id: str,
    allow_prepare: tuple[str, ...] = (),
    allow_perform: tuple[str, ...] = (),
) -> OperatingCharter:
    """Persist a valid profile charter, extending authority only when required."""
    base = default_operating_charter()
    may_prepare = set(base.may_prepare)
    may_perform = set(base.may_perform)
    never_do = set(base.never_do)
    for action in allow_prepare:
        may_perform.discard(action)
        never_do.discard(action)
        may_prepare.add(action)
    for action in allow_perform:
        may_prepare.discard(action)
        never_do.discard(action)
        may_perform.add(action)
    charter = OperatingCharter(
        schema_version=base.schema_version,
        may_prepare=tuple(sorted(may_prepare)),
        may_perform=tuple(sorted(may_perform)),
        never_do=tuple(sorted(never_do)),
        approval_mode=base.approval_mode,
        escalation_email=None,
        escalation_phone=None,
        source="profile",
    )
    repository = BusinessProfileRepository(session)
    profile = repository.get_or_create_active_profile(tenant_id=tenant_id)
    current = inspect_operating_charter(approved_facts=profile.approved_facts)
    repository.upsert_operating_charter(
        profile=profile,
        charter=charter,
        expected_revision=current.revision,
        actor_id="integration-test",
        updated_at=datetime.now(UTC),
        provenance_metadata={"purpose": "runtime_authority_fixture"},
    )
    return charter
