#!/usr/bin/env python3
"""
sync_firecrawl.py

Fetch/merge upstream changes while keeping local tooling/output intact.

Steps:
1. Verify clean working tree (abort if dirty).
2. Archive protected directories (defaults: tools/, output/).
3. Fetch & merge upstream branch into current branch.
4. Restore archived directories and stage them so their content remains unchanged.

Usage:
    python tools/sync_firecrawl.py
    python tools/sync_firecrawl.py --remote upstream --branch main --protected tools,output
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTECTED = ("tools", "output")


class CommandError(RuntimeError):
    """Raised when a git command fails."""


def run_git(args: list[str]) -> str:
    """Run a git command in the repository root and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise CommandError(
            f"git {' '.join(args)} failed ({result.returncode}):\n{result.stderr.strip()}"
        )
    if result.stdout:
        print(result.stdout.strip())
    return result.stdout


def ensure_clean_worktree() -> None:
    status = run_git(["status", "--porcelain"]).strip()
    if status:
        raise SystemExit(
            "Working tree is not clean. Commit or stash changes before running this script."
        )


def archive_paths(paths: list[Path]) -> dict[Path, Path]:
    """Copy protected directories into temp folders and return mapping."""
    archives: dict[Path, Path] = {}
    for path in paths:
        if not path.exists():
            continue
        temp_dir = Path(tempfile.mkdtemp(prefix=f"firecrawl-{path.name}-"))
        snapshot = temp_dir / path.name
        shutil.copytree(path, snapshot)
        archives[path] = snapshot
    return archives


def restore_paths(archives: dict[Path, Path]) -> None:
    for original, snapshot in archives.items():
        if original.exists():
            shutil.rmtree(original)
        shutil.copytree(snapshot, original)


def stage_paths(paths: list[Path]) -> None:
    existing = [str(path.relative_to(REPO_ROOT)) for path in paths if path.exists()]
    if existing:
        run_git(["add", *existing])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync upstream changes while keeping tools/ and output/ intact."
    )
    parser.add_argument(
        "--remote",
        default="upstream",
        help="Remote name to fetch (default: upstream)",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Remote branch to merge (default: main)",
    )
    parser.add_argument(
        "--protected",
        default=",".join(DEFAULT_PROTECTED),
        help="Comma-separated directories to preserve (default: tools,output)",
    )
    args = parser.parse_args()

    protected_paths = [
        (REPO_ROOT / entry.strip()) for entry in args.protected.split(",") if entry.strip()
    ]

    print("Checking for clean working tree...")
    ensure_clean_worktree()

    print("Archiving protected paths...")
    archives = archive_paths(protected_paths)

    target_ref = f"{args.remote}/{args.branch}"
    print(f"Fetching {target_ref}...")
    run_git(["fetch", args.remote, args.branch])

    print(f"Merging {target_ref} into current branch...")
    try:
        run_git(["merge", "--no-edit", target_ref])
    except CommandError as merge_error:
        print("Merge failed. Restoring protected paths before exiting.")
        if archives:
            restore_paths(archives)
        raise SystemExit(str(merge_error))

    if archives:
        print("Restoring protected paths...")
        restore_paths(archives)
        stage_paths(protected_paths)
        print("Protected paths restored and staged.")

    print("Sync complete. Review and commit as needed.")


if __name__ == "__main__":
    main()
