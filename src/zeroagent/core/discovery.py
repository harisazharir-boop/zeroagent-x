"""Bounded, deterministic, read-only workspace file discovery."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

DEFAULT_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)


@dataclass(frozen=True)
class DiscoveryLimits:
    """Traversal bounds. Size limit skips files but does not read their content."""

    max_files: int = 10_000
    max_file_size_bytes: int = 5_000_000
    max_directory_depth: int = 20


@dataclass
class DiscoveryResult:
    files: list[Path] = field(default_factory=list)
    directory_count: int = 0
    warnings: list[str] = field(default_factory=list)
    complete: bool = True


def _load_ignore_spec(workspace: Path, warnings: list[str]) -> pathspec.PathSpec:
    ignore_file = workspace / ".gitignore"
    try:
        lines = ignore_file.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    except (OSError, UnicodeError) as error:
        warnings.append(f"Could not read .gitignore: {error}")
        lines = []
    return pathspec.GitIgnoreSpec.from_lines(lines)


def discover_files(workspace: Path, limits: DiscoveryLimits) -> DiscoveryResult:
    """Discover regular files below workspace without following any symlinks."""
    result = DiscoveryResult()
    ignore_spec = _load_ignore_spec(workspace, result.warnings)
    pending: list[tuple[Path, int]] = [(workspace, 0)]

    while pending:
        directory, depth = pending.pop()
        try:
            with os.scandir(directory) as entries:
                ordered_entries = sorted(
                    entries, key=lambda entry: (entry.name.casefold(), entry.name)
                )
        except OSError as error:
            result.warnings.append(
                f"Unreadable directory {directory.relative_to(workspace)}: {error}"
            )
            result.complete = False
            continue

        for entry in ordered_entries:
            path = Path(entry.path)
            relative = path.relative_to(workspace).as_posix()
            try:
                if entry.is_symlink():
                    result.warnings.append(f"Skipped symbolic link: {relative}")
                    continue
                is_directory = entry.is_dir(follow_symlinks=False)
                if is_directory:
                    if (
                        entry.name in DEFAULT_IGNORED_DIRECTORIES
                        or ignore_spec.match_file(f"{relative}/")
                    ):
                        continue
                    if depth >= limits.max_directory_depth:
                        result.warnings.append(
                            f"Directory depth limit reached: {relative}"
                        )
                        result.complete = False
                        continue
                    result.directory_count += 1
                    pending.append((path, depth + 1))
                    continue
                if not entry.is_file(follow_symlinks=False) or ignore_spec.match_file(
                    relative
                ):
                    continue
                if (
                    entry.stat(follow_symlinks=False).st_size
                    > limits.max_file_size_bytes
                ):
                    result.warnings.append(f"Skipped oversized file: {relative}")
                    result.complete = False
                    continue
            except OSError as error:
                result.warnings.append(f"Unreadable entry {relative}: {error}")
                result.complete = False
                continue
            if len(result.files) >= limits.max_files:
                result.warnings.append("File count limit reached")
                result.complete = False
                return result
            result.files.append(path)
    result.files.sort(
        key=lambda file: (
            file.relative_to(workspace).as_posix().casefold(),
            file.relative_to(workspace).as_posix(),
        )
    )
    return result
