"""Small helpers for interacting with git."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute a git command."""
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def is_git_repo() -> bool:
    """Return True if the current directory is inside a git worktree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout.strip() == "true"
    except subprocess.CalledProcessError:
        return False


def auto_commit(paths: Iterable[Path], message: str) -> None:
    """Stage the provided paths and create a commit."""
    path_strings = [str(path) for path in paths]
    if not path_strings:
        return
    _run_git(["add", *path_strings])
    _run_git(["commit", "-m", message])

