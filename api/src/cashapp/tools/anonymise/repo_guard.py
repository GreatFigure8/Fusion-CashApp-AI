"""Path guards: source data and keys must live outside the git work tree.

Containment is checked on resolved paths with ``is_relative_to``, never by string prefix.
"""

from __future__ import annotations

from pathlib import Path


class PathGuardError(Exception):
    """A path breaks a containment rule (inside the repo, or output inside the source)."""


def find_repo_root(start: Path) -> Path | None:
    """Nearest ancestor holding a ``.git`` directory or file (a file means a worktree)."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _nearest_existing(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def ensure_outside_repo(path: Path, *, what: str, cwd: Path | None = None) -> Path:
    """Return the resolved ``path``; raise when it lies inside any git work tree.

    Both the work tree around the current directory and any work tree found above the path
    itself are checked, so a key or source folder cannot hide in a sibling checkout either.
    """
    resolved = path.expanduser().resolve()
    roots: list[Path] = []
    cwd_root = find_repo_root(cwd if cwd is not None else Path.cwd())
    if cwd_root is not None:
        roots.append(cwd_root)
    own_root = find_repo_root(_nearest_existing(resolved))
    if own_root is not None:
        roots.append(own_root)
    for root in roots:
        if resolved.is_relative_to(root):
            raise PathGuardError(f"{what} must be outside the git work tree")
    return resolved


def ensure_not_inside(child: Path, parent: Path, *, what: str) -> None:
    """Raise when ``child`` resolves to ``parent`` or somewhere beneath it."""
    if child.expanduser().resolve().is_relative_to(parent.expanduser().resolve()):
        raise PathGuardError(what)
