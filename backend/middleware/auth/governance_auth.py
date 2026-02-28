"""
Governance-Enhanced Authentication
Auth middleware with governance authority levels

Built with Pride for Obex Blackvault
"""

from fastapi import Depends, HTTPException, status
import logging

from backend.middleware.auth.auth_middleware import get_current_user
from backend.models.domain.user import User, UserRole
from backend.database.session import get_db
from backend.database.repositories import AuditRepository
from backend.database.governance_models import AuthorityLevel
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


# Map UserRole to AuthorityLevel
ROLE_TO_AUTHORITY = {
    UserRole.VIEWER: AuthorityLevel.GUEST,
    UserRole.OPERATOR: AuthorityLevel.OPERATOR,
    UserRole.DEVELOPER: AuthorityLevel.USER,
    UserRole.ADMIN: AuthorityLevel.ADMIN,
}


def get_authority_level(user: User) -> AuthorityLevel:
    """
    Get governance authority level for user

    Args:
        user: User object

    Returns:
        AuthorityLevel enum
    """
    return ROLE_TO_AUTHORITY.get(user.role, AuthorityLevel.GUEST)


def require_authority(required_authority: AuthorityLevel):
    """
    Dependency factory for governance authority-based access control

    Usage:
        @app.post("/approve-high-risk")
        async def approve_high_risk(
            current_user: User = Depends(require_authority(AuthorityLevel.ADMIN))
        ):
            return {"message": "Approval granted"}

    Args:
        required_authority: Minimum authority level required

    Returns:
        Dependency function
    """

    async def authority_checker(current_user: User = Depends(get_current_user)) -> User:
        """
        Check if user has required authority level

        Args:
            current_user: Authenticated user

        Returns:
            User if authorized

        Raises:
            HTTPException: If insufficient authority
        """
        authority_hierarchy = {
            AuthorityLevel.GUEST: 0,
            AuthorityLevel.USER: 1,
            AuthorityLevel.OPERATOR: 2,
            AuthorityLevel.ADMIN: 3,
            AuthorityLevel.COMPLIANCE_OFFICER: 4,
        }

        user_authority = get_authority_level(current_user)
        user_level = authority_hierarchy.get(user_authority, 0)
        required_level = authority_hierarchy.get(required_authority, 999)

        if user_level < required_level:
            # Audit unauthorized access attempt
            try:
                db = next(get_db())
                audit_repo = AuditRepository(db)
                audit_repo.create_event(
                    id=str(uuid.uuid4()),
                    tenant_id=current_user.tenant_id,
                    event_type="unauthorized_access_attempt",
                    event_category="security",
                    severity="warning",
                    actor_id=current_user.id,
                    actor_type="user",
                    outcome="blocked",
                    event_data={
                        "required_authority": required_authority.value,
                        "user_authority": user_authority.value,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception as e:
                logger.error(f"Failed to audit unauthorized access: {e}")

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient authority. Required: {required_authority.value}, You have: {user_authority.value}",  # noqa: E501
            )

        return current_user

    return authority_checker


async def get_current_user_with_audit(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Get current user and audit the access

    Use this for sensitive operations that need audit trail

    Args:
        current_user: Authenticated user

    Returns:
        User object
    """
    try:
        db = next(get_db())
        audit_repo = AuditRepository(db)
        audit_repo.create_event(
            id=str(uuid.uuid4()),
            tenant_id=current_user.tenant_id,
            event_type="authenticated_access",
            event_category="access",
            severity="info",
            actor_id=current_user.id,
            actor_type="user",
            outcome="success",
            event_data={
                "role": current_user.role.value,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        logger.error(f"Failed to audit access: {e}")

    return current_user


def require_compliance_officer():
    """
    Dependency for compliance officer only access

    Usage:
        @app.post("/compliance/override")
        async def compliance_override(
            current_user: User = Depends(require_compliance_officer())
        ):
            return {"message": "Compliance override granted"}
    """
    return require_authority(AuthorityLevel.COMPLIANCE_OFFICER)


def can_approve_risk_tier(user: User, risk_tier: str) -> bool:
    """
    Check if user can approve operations for given risk tier

    Args:
        user: User object
        risk_tier: Risk tier (minimal, limited, high, unacceptable)

    Returns:
        True if user can approve
    """
    authority = get_authority_level(user)

    # Authority requirements by risk tier
    tier_requirements = {
        "minimal": AuthorityLevel.USER,
        "limited": AuthorityLevel.OPERATOR,
        "high": AuthorityLevel.ADMIN,
        "unacceptable": AuthorityLevel.COMPLIANCE_OFFICER,
    }

    required = tier_requirements.get(risk_tier, AuthorityLevel.ADMIN)

    authority_hierarchy = {
        AuthorityLevel.GUEST: 0,
        AuthorityLevel.USER: 1,
        AuthorityLevel.OPERATOR: 2,
        AuthorityLevel.ADMIN: 3,
        AuthorityLevel.COMPLIANCE_OFFICER: 4,
    }

    return authority_hierarchy.get(authority, 0) >= authority_hierarchy.get(required, 999)


def get_approval_authority_for_user(user: User) -> str:
    """
    Get highest risk tier user can approve

    Args:
        user: User object

    Returns:
        Risk tier string
    """
    authority = get_authority_level(user)

    authority_to_tier = {
        AuthorityLevel.GUEST: None,
        AuthorityLevel.USER: "minimal",
        AuthorityLevel.OPERATOR: "limited",
        AuthorityLevel.ADMIN: "high",
        AuthorityLevel.COMPLIANCE_OFFICER: "unacceptable",
    }

    return authority_to_tier.get(authority)
