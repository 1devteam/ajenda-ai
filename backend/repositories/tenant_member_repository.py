"""TenantMemberRepository — membership registry data access."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.tenant_member import TenantMember


class TenantMemberRepository:
    """Data access for tenant membership rows."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        email_raw: str,
        email_canonical: str,
        role: str = "tenant_owner",
        status: str = "pending_verification",
        external_subject_id: str | None = None,
        password_hash: str | None = None,
        verification_token_hash: str | None = None,
        verification_expires_at: datetime | None = None,
        verification_delivery_status: str | None = None,
    ) -> TenantMember:
        """Persist a new membership row. Caller must flush/commit."""
        member = TenantMember(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            email_raw=email_raw,
            email_canonical=email_canonical,
            role=role,
            status=status,
            external_subject_id=external_subject_id,
            password_hash=password_hash,
            verification_token_hash=verification_token_hash,
            verification_expires_at=verification_expires_at,
            verification_delivery_status=verification_delivery_status,
        )
        self._session.add(member)
        return member

    def get(self, member_id: uuid.UUID) -> TenantMember | None:
        return self._session.get(TenantMember, member_id)

    def get_owner_by_email_canonical(
        self,
        email_canonical: str,
        *,
        statuses: frozenset[str] | None = None,
    ) -> TenantMember | None:
        """Return the tenant_owner row for a canonical email, if any."""
        allowed = statuses or frozenset({"active", "pending_verification"})
        stmt = (
            select(TenantMember)
            .where(
                TenantMember.email_canonical == email_canonical,
                TenantMember.role == "tenant_owner",
                TenantMember.status.in_(allowed),
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_pending_owner_by_email_for_update(self, email_canonical: str) -> TenantMember | None:
        """Lock one pending owner row until the caller commits or rolls back.

        Verification and resend flows use the same row as the single-use authority.
        Serializing on that row prevents two concurrent requests from consuming or
        replacing the same verification authority at once.
        """
        stmt = (
            select(TenantMember)
            .where(
                TenantMember.email_canonical == email_canonical,
                TenantMember.role == "tenant_owner",
                TenantMember.status == "pending_verification",
            )
            .limit(1)
            .with_for_update()
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_active_owner_for_tenant(self, tenant_id: uuid.UUID) -> TenantMember | None:
        """Return the active tenant_owner membership row for a tenant, if any."""
        stmt = (
            select(TenantMember)
            .where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.role == "tenant_owner",
                TenantMember.status == "active",
            )
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_by_tenant_and_email(
        self,
        tenant_id: uuid.UUID,
        email_canonical: str,
    ) -> TenantMember | None:
        stmt = select(TenantMember).where(
            TenantMember.tenant_id == tenant_id,
            TenantMember.email_canonical == email_canonical,
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def get_active_by_external_subject_id(self, external_subject_id: str) -> TenantMember | None:
        stmt = (
            select(TenantMember)
            .where(
                TenantMember.external_subject_id == external_subject_id,
                TenantMember.status == "active",
            )
            .order_by(TenantMember.created_at)
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    def link_external_subject(self, member: TenantMember, *, external_subject_id: str) -> TenantMember:
        member.external_subject_id = external_subject_id
        member.updated_at = datetime.now(tz=UTC)
        return member

    def list_active_for_email(self, email_canonical: str) -> list[TenantMember]:
        stmt = (
            select(TenantMember)
            .where(
                TenantMember.email_canonical == email_canonical,
                TenantMember.status == "active",
            )
            .order_by(TenantMember.created_at)
        )
        return list(self._session.execute(stmt).scalars().all())

    def mark_verification_delivery_failed(self, member_id: uuid.UUID) -> TenantMember | None:
        member = self.get(member_id)
        if member is None:
            return None
        member.verification_delivery_status = "failed"
        member.updated_at = datetime.now(tz=UTC)
        return member

    def list_pending_with_verification_tokens(self) -> list[TenantMember]:
        stmt = (
            select(TenantMember)
            .where(
                TenantMember.status == "pending_verification",
                TenantMember.verification_token_hash.is_not(None),
            )
            .order_by(TenantMember.created_at.desc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def activate_member(self, member: TenantMember, *, verified_at: datetime) -> TenantMember:
        member.status = "active"
        member.verified_at = verified_at
        member.verification_token_hash = None
        member.verification_expires_at = None
        member.verification_delivery_status = "sent"
        member.updated_at = verified_at
        return member

    def update_verification_token(
        self,
        member: TenantMember,
        *,
        token_hash: str,
        expires_at: datetime,
        delivery_status: str = "pending",
    ) -> TenantMember:
        member.verification_token_hash = token_hash
        member.verification_expires_at = expires_at
        member.verification_delivery_status = delivery_status
        member.updated_at = datetime.now(tz=UTC)
        return member
