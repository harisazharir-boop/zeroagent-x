"""Stable release version has one authoritative metadata source."""

from __future__ import annotations

import tomllib
from pathlib import Path

from zeroagent import __version__


def test_runtime_version_matches_project_metadata() -> None:
    project_file = Path(__file__).parents[1] / "pyproject.toml"
    with project_file.open("rb") as file:
        metadata_version = tomllib.load(file)["project"]["version"]

    assert metadata_version == "1.0.0"
    assert __version__ == metadata_version
