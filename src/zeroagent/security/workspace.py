"""Explicit workspace validation for read-only repository analysis."""

from pathlib import Path


class WorkspaceError(ValueError):
    """Raised when selected workspace cannot be used safely."""


def validate_workspace(path: Path) -> Path:
    """Resolve explicitly selected directory without allowing implicit fallbacks."""
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise WorkspaceError(f"Cannot resolve workspace: {path}") from error
    if not resolved.is_dir():
        raise WorkspaceError(f"Workspace is not a directory: {path}")
    return resolved
