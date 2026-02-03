#!/usr/bin/env python3
"""
Version Bump Script
Automates version bumping with semantic versioning

Usage:
    python scripts/bump_version.py major  # 5.0.0 -> 6.0.0
    python scripts/bump_version.py minor  # 5.0.0 -> 5.1.0
    python scripts/bump_version.py patch  # 5.0.0 -> 5.0.1

Built with Pride for Obex Blackvault
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# Project root
PROJECT_ROOT = Path(__file__).parent.parent
VERSION_FILE = PROJECT_ROOT / "VERSION"
CHANGELOG_FILE = PROJECT_ROOT / "CHANGELOG.md"


def get_current_version() -> tuple[int, int, int]:
    """Read current version from VERSION file"""
    version = VERSION_FILE.read_text().strip()
    parts = version.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def bump_version(bump_type: str) -> str:
    """
    Bump version based on type
    
    Args:
        bump_type: 'major', 'minor', or 'patch'
    
    Returns:
        New version string
    """
    major, minor, patch = get_current_version()
    
    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid bump type: {bump_type}. Use 'major', 'minor', or 'patch'")
    
    return f"{major}.{minor}.{patch}"


def update_version_file(new_version: str):
    """Write new version to VERSION file"""
    VERSION_FILE.write_text(new_version + "\n")
    print(f"✅ Updated VERSION file to {new_version}")


def update_changelog(new_version: str):
    """Add new version section to CHANGELOG"""
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Read current changelog
    changelog = CHANGELOG_FILE.read_text()
    
    # Find the insertion point (after the header)
    lines = changelog.split("\n")
    insert_index = 0
    for i, line in enumerate(lines):
        if line.startswith("## ["):
            insert_index = i
            break
    
    # Create new version section
    new_section = f"""## [{new_version}] - {today}

### Added
- 

### Changed
- 

### Fixed
- 

### Removed
- 

---

"""
    
    # Insert new section
    lines.insert(insert_index, new_section)
    
    # Write back
    CHANGELOG_FILE.write_text("\n".join(lines))
    print(f"✅ Added version {new_version} section to CHANGELOG.md")


def git_commit_and_tag(new_version: str):
    """Create git commit and tag for version bump"""
    try:
        # Stage files
        subprocess.run(["git", "add", "VERSION", "CHANGELOG.md"], check=True, cwd=PROJECT_ROOT)
        
        # Commit
        commit_message = f"chore: Bump version to {new_version}"
        subprocess.run(["git", "commit", "-m", commit_message], check=True, cwd=PROJECT_ROOT)
        
        # Create tag
        tag_name = f"v{new_version}"
        tag_message = f"Release {new_version}"
        subprocess.run(["git", "tag", "-a", tag_name, "-m", tag_message], check=True, cwd=PROJECT_ROOT)
        
        print(f"✅ Created git commit and tag {tag_name}")
        print(f"\n📦 To push: git push origin v5.0-working && git push origin {tag_name}")
        
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Git operations failed: {e}")
        print("   You can manually commit and tag:")
        print(f"   git add VERSION CHANGELOG.md")
        print(f"   git commit -m 'chore: Bump version to {new_version}'")
        print(f"   git tag -a v{new_version} -m 'Release {new_version}'")


def main():
    """Main entry point"""
    if len(sys.argv) != 2:
        print("Usage: python scripts/bump_version.py [major|minor|patch]")
        sys.exit(1)
    
    bump_type = sys.argv[1].lower()
    
    if bump_type not in ["major", "minor", "patch"]:
        print(f"❌ Invalid bump type: {bump_type}")
        print("   Use 'major', 'minor', or 'patch'")
        sys.exit(1)
    
    # Get current and new versions
    current = ".".join(map(str, get_current_version()))
    new_version = bump_version(bump_type)
    
    print("=" * 60)
    print(f"Version Bump: {current} -> {new_version} ({bump_type})")
    print("=" * 60)
    
    # Confirm
    response = input(f"\nBump version from {current} to {new_version}? [y/N] ")
    if response.lower() != "y":
        print("❌ Cancelled")
        sys.exit(0)
    
    # Perform bump
    update_version_file(new_version)
    update_changelog(new_version)
    git_commit_and_tag(new_version)
    
    print("\n" + "=" * 60)
    print(f"✅ Version bumped to {new_version}")
    print("=" * 60)
    print("\nNext steps:")
    print(f"1. Edit CHANGELOG.md and fill in changes for {new_version}")
    print("2. Commit the changelog updates")
    print("3. Push to remote: git push origin v5.0-working && git push origin v{new_version}")


if __name__ == "__main__":
    main()
