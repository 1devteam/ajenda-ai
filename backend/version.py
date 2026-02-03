"""
Version Management Module
Handles version information for Omnipath

Built with Pride for Obex Blackvault
"""
from pathlib import Path
from typing import Tuple

# Version file location
VERSION_FILE = Path(__file__).parent.parent / "VERSION"


def get_version() -> str:
    """
    Get the current version from VERSION file
    
    Returns:
        Version string (e.g., "5.0.0")
    """
    try:
        return VERSION_FILE.read_text().strip()
    except FileNotFoundError:
        return "0.0.0"


def get_version_tuple() -> Tuple[int, int, int]:
    """
    Get version as tuple of integers
    
    Returns:
        Tuple of (major, minor, patch)
    """
    version = get_version()
    parts = version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def get_version_info() -> dict:
    """
    Get comprehensive version information
    
    Returns:
        Dictionary with version details
    """
    version = get_version()
    major, minor, patch = get_version_tuple()
    
    return {
        "version": version,
        "major": major,
        "minor": minor,
        "patch": patch,
        "full": f"Omnipath v{version}",
        "api_version": "v1"
    }


# Module-level constants
__version__ = get_version()
VERSION = __version__
VERSION_INFO = get_version_info()

# Expose for easy import
__all__ = ["__version__", "VERSION", "VERSION_INFO", "get_version", "get_version_tuple", "get_version_info"]
