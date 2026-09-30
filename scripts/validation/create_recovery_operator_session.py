#!/usr/bin/env python3
"""Create a short-lived Ajenda session token for an isolated recovery proof."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.auth.session_token import SessionTokenService
from backend.domain.customer_auth_session import CustomerAuthSession
from backend.domain.tenant import Tenant
from backend.domain.tenant_member import TenantMember


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--ttl-minutes", type=int, default=15, choices=range(1, 31))
    parser.add_argument("--confirm-isolated", action="store_true")
    args = parser.parse_args()

    if not args.confirm_isolated:
        raise SystemExit("refusing to create a session without --confirm-isolated")
    if os.environ.get("AJENDA_ENV", "").strip().lower() == "production":
        raise SystemExit("refusing to create a session when AJENDA_ENV=production")
    if os.environ.get("AJENDA_VALIDATION_ENV", "").strip().lower() != "isolated":
        raise SystemExit("set AJENDA_VALIDATION_ENV=isolated before creating the session")
    try:
        tenant_id = uuid.UUID(args.tenant_id)
    except ValueError as exc:
        raise SystemExit("--tenant-id must be a UUID") from exc

    database_url = os.environ.get("AJENDA_DATABASE_URL", os.environ.get("AJENDA_DB_URL", "")).strip()
    signing_secret = os.environ.get("AJENDA_SESSION_SIGNING_SECRET", "").strip()
    if not database_url or len(signing_secret) < 32:
        raise SystemExit("set AJENDA_DATABASE_URL/AJENDA_DB_URL and a 32+ character AJENDA_SESSION_SIGNING_SECRET")

    engine = create_engine(database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session: Session = factory()
    try:
        tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None or not tenant.slug.startswith("recovery-seed-"):
            raise SystemExit("refusing: tenant is not a recovery-seed tenant")

        operator_email = f"recovery-operator+{tenant_id}@isolated.invalid"
        member = session.scalar(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.email_canonical == operator_email,
            )
        )
        if member is None:
            member = TenantMember(
                tenant_id=tenant_id,
                email_raw=operator_email,
                email_canonical=operator_email,
                role="tenant_owner",
                status="active",
                external_subject_id=f"recovery-operator:{tenant_id}",
                verified_at=datetime.now(UTC),
            )
            session.add(member)
            session.flush()

        token_service = SessionTokenService(
            signing_secret=signing_secret,
            access_ttl_seconds=args.ttl_minutes * 60,
        )
        token, expires_at = token_service.issue_access_token(
            member_id=member.id,
            tenant_id=tenant_id,
            email=member.email_canonical,
            roles=("admin",),
        )
        refresh_secret = secrets.token_urlsafe(48)
        refresh_hash = hashlib.sha256(refresh_secret.encode("utf-8")).hexdigest()
        session.add(
            CustomerAuthSession(
                member_id=member.id,
                tenant_id=tenant_id,
                access_jti=token_service.validate_access_token(token).jti,
                refresh_token_hash=refresh_hash,
                expires_at=expires_at,
                refresh_expires_at=expires_at,
            )
        )
        session.commit()
        print(f"expires_at={expires_at.isoformat()}")
        print(f"AJENDA_AUTH_HEADER=Bearer {token}")
    finally:
        session.close()
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
