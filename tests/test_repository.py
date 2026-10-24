"""Tests for deterministic, read-only repository analysis."""

from pathlib import Path

import pytest

from zeroagent.core.discovery import DiscoveryLimits, discover_files
from zeroagent.core.repository import analyze_repository, detect_language
from zeroagent.security.workspace import WorkspaceError, validate_workspace


def test_workspace_validation_rejects_missing_path_and_file(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        validate_workspace(tmp_path / "missing")
    file_path = tmp_path / "file.txt"
    file_path.write_text("x")
    with pytest.raises(WorkspaceError):
        validate_workspace(file_path)


def test_workspace_symlink_resolves_only_explicit_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    selected = tmp_path / "selected"
    try:
        selected.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Symbolic links unavailable")
    assert validate_workspace(selected) == target.resolve()


def test_discovery_ignores_symlink_and_generated_directories(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("pass")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "skip.js").write_text("")
    external = tmp_path.parent / "outside-zeroagent-test.txt"
    external.write_text("outside")
    try:
        (tmp_path / "outside-link").symlink_to(external)
    except OSError:
        pytest.skip("Symbolic links unavailable")
    result = discover_files(tmp_path, DiscoveryLimits())
    assert [file.relative_to(tmp_path).as_posix() for file in result.files] == [
        "src/main.py"
    ]
    assert any("symbolic link" in warning for warning in result.warnings)


def test_discovery_respects_gitignore_limits_and_order(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored/\n*.secret\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored" / "skip.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "a.py").write_text("")
    (tmp_path / "token.secret").write_text("")
    result = discover_files(tmp_path, DiscoveryLimits(max_files=2))
    assert [file.name for file in result.files] == [".gitignore", "a.py"]
    assert result.complete is False


def test_discovery_respects_size_and_depth_limits(tmp_path: Path) -> None:
    (tmp_path / "large.py").write_text("x" * 20)
    nested = tmp_path / "one" / "two"
    nested.mkdir(parents=True)
    (nested / "deep.py").write_text("")
    result = discover_files(
        tmp_path, DiscoveryLimits(max_file_size_bytes=10, max_directory_depth=1)
    )
    assert result.files == []
    assert result.complete is False
    assert any("oversized" in warning for warning in result.warnings)
    assert any("depth limit" in warning for warning in result.warnings)


def test_discovery_records_permission_error(tmp_path: Path, monkeypatch) -> None:
    import zeroagent.core.discovery as discovery

    original_scandir = discovery.os.scandir

    def deny_root(path: Path):
        if Path(path) == tmp_path:
            raise PermissionError("denied")
        return original_scandir(path)

    monkeypatch.setattr(discovery.os, "scandir", deny_root)
    result = discover_files(tmp_path, DiscoveryLimits())
    assert result.complete is False
    assert any("Unreadable directory" in warning for warning in result.warnings)


def test_language_detection_and_distribution(tmp_path: Path) -> None:
    for name in ["a.py", "b.py", "site.ts", "README.md", "blob.xyz"]:
        (tmp_path / name).write_text("")
    report = analyze_repository(tmp_path)
    stats = {item.language: item for item in report.languages}
    assert detect_language(Path("unknown.xyz")) == "Unknown"
    assert stats["Python"].file_count == 2
    assert stats["Python"].percentage == 40.0
    assert stats["Unknown"].file_count == 1


def test_manifest_detection_and_dependency_parsing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'fixture'\ndependencies = ['pydantic>=2']\n"
        "[project.optional-dependencies]\ntest = ['pytest>=8']\n"
    )
    (tmp_path / "requirements.txt").write_text("pytest>=8\n-r extras.txt\n")
    (tmp_path / "package.json").write_text('{"dependencies":{"react":"^19"}}')
    (tmp_path / "Cargo.toml").write_text("[package]\nname = 'fixture'\n")
    (tmp_path / "go.mod").write_text("module fixture\n")
    report = analyze_repository(tmp_path)
    assert report.ecosystems == ["go", "javascript", "python", "rust"]
    assert [dependency.name for dependency in report.dependencies] == [
        "react",
        "pydantic",
        "pytest",
        "pytest",
    ]
    assert any(warning.code == "unsupported_requirement" for warning in report.warnings)
    assert all(
        not Path(item.evidence["file"]).is_absolute() for item in report.evidence
    )
    assert any(item.finding_type == "language_detection" for item in report.evidence)


def test_malformed_manifests_are_warnings(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project")
    (tmp_path / "package.json").write_text("{")
    report = analyze_repository(tmp_path)
    assert report.complete is False
    assert [warning.code for warning in report.warnings].count(
        "malformed_manifest"
    ) == 2
