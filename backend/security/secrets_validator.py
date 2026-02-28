"""
Secrets Validation for Omnipath v2
Validates that all required secrets are set and not using insecure defaults
at application startup.

Built with Pride for Obex Blackvault
"""

import os
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)


class SecretsValidationError(Exception):
    """Raised when required secrets are missing or insecure in production."""


# Secrets that MUST be set in production and must not use default values
_REQUIRED_PRODUCTION_SECRETS: List[Tuple[str, str]] = [
    ("JWT_SECRET_KEY", "Change this in production"),
    ("SECRET_KEY", ""),
]

# Default/insecure values that must not appear in production
_INSECURE_DEFAULTS: List[str] = [
    "changeme",
    "change_me",
    "secret",
    "password",
    "admin",
    "omnipath",  # default DB password used in dev docker-compose
    "your-secret-key-here",
    "Change this in production",
    "",
]

# Minimum lengths for cryptographic secrets
_MIN_SECRET_LENGTH = 32


def validate_secrets(environment: str = "development") -> None:
    """
    Validate that all required secrets are properly configured.

    In production:
    - All required secrets must be set.
    - No secret may use a known insecure default value.
    - Cryptographic secrets must meet minimum length requirements.

    In development/staging:
    - Missing or weak secrets generate warnings, not errors.

    Args:
        environment: The current deployment environment.

    Raises:
        SecretsValidationError: If validation fails in production.
    """
    is_production = environment == "production"
    issues: List[str] = []

    for env_var, default_value in _REQUIRED_PRODUCTION_SECRETS:
        value = os.getenv(env_var, default_value)

        # Check if unset or empty
        if not value:
            issues.append(f"{env_var} is not set")
            continue

        # Check against known insecure defaults
        if value.lower() in [d.lower() for d in _INSECURE_DEFAULTS if d]:
            issues.append(f"{env_var} is using an insecure default value")
            continue

        # Check minimum length for cryptographic secrets
        if len(value) < _MIN_SECRET_LENGTH:
            issues.append(
                f"{env_var} is too short ({len(value)} chars, minimum {_MIN_SECRET_LENGTH})"
            )

    # Check database password separately
    db_url = os.getenv("DATABASE_URL", "")
    if db_url and is_production:
        if ":omnipath@" in db_url or ":password@" in db_url or ":changeme@" in db_url:
            issues.append("DATABASE_URL contains a default/insecure password")

    # Check Redis password in production
    redis_url = os.getenv("REDIS_URL", "")
    if redis_url and is_production and "://:@" not in redis_url and "@" not in redis_url:
        # Redis URL without authentication in production
        issues.append("REDIS_URL does not include authentication credentials in production")

    if issues:
        message = "Secrets validation failed:\n" + "\n".join(f"  - {i}" for i in issues)
        if is_production:
            logger.critical(message)
            raise SecretsValidationError(message)
        else:
            logger.warning(message)
    else:
        logger.info("✅ Secrets validation passed")
