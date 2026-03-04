#!/usr/bin/env python3
"""
Citadel AI — Automatic Version Bump Script
==========================================
Reads commits since the last git tag, determines the appropriate
semantic version bump (major/minor/patch), updates VERSION, CHANGELOG.md,
and docker-compose.staging.yml, then commits and tags.

Conventional Commits mapping:
  feat!: / BREAKING CHANGE  → MAJOR
  feat:                      → MINOR
  fix: / perf: / refactor:   → PATCH
  chore: / docs: / style: / test: / ci: → NO BUMP

Built with Pride for Obex Blackvault
"""
import subprocess
import sys
import re
from datetime import datetime, timezone
from pathlib import Path


# ── Configuration ────────────────────────────────────────────────────────────

# Script lives at scripts/bump_version.py — repo root is one level up
REPO_ROOT = Path(__file__).parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
CHANGELOG_FILE = REPO_ROOT / "CHANGELOG.md"
COMPOSE_FILE = REPO_ROOT / "docker-compose.staging.yml"

# BREAKING CHANGE must appear as a git trailer footer ("BREAKING CHANGE: ..."
# or "BREAKING-CHANGE: ...") at the START of a line, not anywhere in body text.
MAJOR_PATTERNS = [
    r"^feat!:",
    r"^fix!:",
    r"^refactor!:",
    r"^BREAKING CHANGE:",
    r"^BREAKING-CHANGE:",
]
MINOR_PATTERNS = [
    r"^feat:",
    r"^feat\(",
]
PATCH_PATTERNS = [
    r"^fix:",
    r"^fix\(",
    r"^perf:",
    r"^perf\(",
    r"^refactor:",
    r"^refactor\(",
    r"^revert:",
]
NO_BUMP_PATTERNS = [
    r"^chore:",
    r"^docs:",
    r"^style:",
    r"^test:",
    r"^ci:",
    r"^build:",
    r"^merge:",
    r"^\[skip",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd: str, check: bool = True) -> str:
    """Run a shell command and return stdout."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, cwd=REPO_ROOT
    )
    if check and result.returncode != 0:
        print(f"ERROR running: {cmd}")
        print(f"  stderr: {result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()


def read_version() -> tuple[int, int, int]:
    """Read current version from VERSION file."""
    raw = VERSION_FILE.read_text().strip()
    parts = raw.split(".")
    if len(parts) != 3:
        print(f"ERROR: VERSION file has unexpected format: {raw!r}")
        sys.exit(1)
    return int(parts[0]), int(parts[1]), int(parts[2])


def write_version(major: int, minor: int, patch: int) -> None:
    """Write new version to VERSION file."""
    VERSION_FILE.write_text(f"{major}.{minor}.{patch}\n")


def get_last_tag() -> str | None:
    """Get the most recent version tag, or None if no tags exist."""
    result = subprocess.run(
        "git tag --sort=-version:refname",
        shell=True, capture_output=True, text=True, cwd=REPO_ROOT
    )
    tags = [t.strip() for t in result.stdout.strip().splitlines() if t.strip()]
    version_tags = [t for t in tags if re.match(r"^v\d+\.\d+\.\d+$", t)]
    return version_tags[0] if version_tags else None


def get_commits_since(ref: str | None) -> list[dict]:
    """Get commits since ref (or all commits if ref is None)."""
    if ref:
        log_range = f"{ref}..HEAD"
    else:
        log_range = "HEAD"

    raw = run(
        f'git log {log_range} --pretty=format:"%H|||%s|||%b|||END"',
        check=False
    )
    if not raw:
        return []

    commits = []
    for block in raw.split("|||END"):
        block = block.strip()
        if not block:
            continue
        parts = block.split("|||", 2)
        if len(parts) < 2:
            continue
        sha = parts[0].strip().strip('"')
        subject = parts[1].strip()
        body = parts[2].strip() if len(parts) > 2 else ""
        commits.append({"sha": sha[:8], "subject": subject, "body": body})

    return commits


def classify_commits(commits: list[dict]) -> tuple[str, list[dict], list[dict], list[dict]]:
    """
    Classify commits and determine bump type.
    Returns (bump_type, major_commits, minor_commits, patch_commits)
    bump_type: 'major' | 'minor' | 'patch' | 'none'
    """
    major_commits, minor_commits, patch_commits = [], [], []

    for commit in commits:
        text = commit["subject"] + "\n" + commit["body"]

        if any(re.search(p, text, re.MULTILINE) for p in MAJOR_PATTERNS):
            major_commits.append(commit)
        elif any(re.search(p, commit["subject"]) for p in MINOR_PATTERNS):
            minor_commits.append(commit)
        elif any(re.search(p, commit["subject"]) for p in PATCH_PATTERNS):
            patch_commits.append(commit)
        # else: no-bump commit (chore, docs, ci, etc.)

    if major_commits:
        return "major", major_commits, minor_commits, patch_commits
    elif minor_commits:
        return "minor", major_commits, minor_commits, patch_commits
    elif patch_commits:
        return "patch", major_commits, minor_commits, patch_commits
    else:
        return "none", [], [], []


def bump(major: int, minor: int, patch: int, bump_type: str) -> tuple[int, int, int]:
    """Calculate new version based on bump type."""
    if bump_type == "major":
        return major + 1, 0, 0
    elif bump_type == "minor":
        return major, minor + 1, 0
    elif bump_type == "patch":
        return major, minor, patch + 1
    else:
        return major, minor, patch


def update_changelog(
    new_version: str,
    major_commits: list[dict],
    minor_commits: list[dict],
    patch_commits: list[dict],
) -> None:
    """Prepend a new section to CHANGELOG.md."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"## [{new_version}] — {today}\n"]

    if major_commits:
        lines.append("\n### Breaking Changes\n")
        for c in major_commits:
            lines.append(f"- {c['subject']} (`{c['sha']}`)\n")

    if minor_commits:
        lines.append("\n### Features\n")
        for c in minor_commits:
            lines.append(f"- {c['subject']} (`{c['sha']}`)\n")

    if patch_commits:
        lines.append("\n### Bug Fixes & Improvements\n")
        for c in patch_commits:
            lines.append(f"- {c['subject']} (`{c['sha']}`)\n")

    lines.append("\n---\n\n")
    new_section = "".join(lines)

    existing = CHANGELOG_FILE.read_text() if CHANGELOG_FILE.exists() else ""
    CHANGELOG_FILE.write_text(new_section + existing)


def update_compose_version(new_version: str) -> None:
    """Update APP_VERSION in docker-compose.staging.yml."""
    if not COMPOSE_FILE.exists():
        print(f"  WARNING: {COMPOSE_FILE} not found, skipping compose update")
        return

    content = COMPOSE_FILE.read_text()
    updated = re.sub(
        r"(APP_VERSION:\s*)\S+",
        f"\\g<1>{new_version}",
        content
    )
    if updated == content:
        print(f"  WARNING: APP_VERSION not found in {COMPOSE_FILE}")
    else:
        COMPOSE_FILE.write_text(updated)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Citadel AI — Auto Version Bump")
    print("=" * 60)

    # 1. Read current version
    major, minor, patch = read_version()
    current_version = f"{major}.{minor}.{patch}"
    print(f"\nCurrent version: {current_version}")

    # 2. Find last tag
    last_tag = get_last_tag()
    print(f"Last git tag:    {last_tag or '(none — scanning all commits)'}")

    # 3. Get commits since last tag
    commits = get_commits_since(last_tag)
    print(f"Commits to scan: {len(commits)}")

    if not commits:
        print("\nNo commits since last tag. Nothing to do.")
        sys.exit(0)

    # 4. Classify commits
    bump_type, major_c, minor_c, patch_c = classify_commits(commits)
    print(f"Bump type:       {bump_type.upper()}")
    print(f"  Breaking:      {len(major_c)}")
    print(f"  Features:      {len(minor_c)}")
    print(f"  Fixes/Perf:    {len(patch_c)}")

    if bump_type == "none":
        print("\nNo version-bumping commits found (only chore/docs/ci).")
        print("No version bump needed.")
        sys.exit(0)

    # 5. Calculate new version
    new_major, new_minor, new_patch = bump(major, minor, patch, bump_type)
    new_version = f"{new_major}.{new_minor}.{new_patch}"
    print(f"\nNew version:     {new_version}")

    # 6. Update files
    print("\nUpdating files...")
    write_version(new_major, new_minor, new_patch)
    print(f"  ✓ VERSION → {new_version}")

    update_changelog(new_version, major_c, minor_c, patch_c)
    print(f"  ✓ CHANGELOG.md prepended")

    update_compose_version(new_version)
    print(f"  ✓ docker-compose.staging.yml APP_VERSION → {new_version}")

    # 7. Git commit
    run('git config user.email "citadel-autoversion@nested-ai.net"')
    run('git config user.name "Citadel AutoVersion"')
    run("git add VERSION CHANGELOG.md docker-compose.staging.yml")
    commit_msg = (
        f"chore(release): bump version {current_version} → {new_version} [skip ci]\n\n"
        f"Auto-generated by bump_version.py\n"
        f"Bump type: {bump_type}\n"
        f"Built with Pride for Obex Blackvault"
    )
    run(f'git commit -m "{commit_msg}"')
    print(f"  ✓ Committed version bump")

    # 8. Create tag
    tag_name = f"v{new_version}"
    run(f'git tag -a {tag_name} -m "Release {tag_name}"')
    print(f"  ✓ Tagged {tag_name}")

    # 9. Push commit + tag
    run("git push origin main")
    run(f"git push origin {tag_name}")
    print(f"  ✓ Pushed to GitHub")

    print(f"\n{'=' * 60}")
    print(f"Release {new_version} complete!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
