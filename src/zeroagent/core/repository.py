"""Deterministic, read-only repository intelligence engine."""

from __future__ import annotations

import json
import re
import tomllib
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from zeroagent import __version__
from zeroagent.core.discovery import DiscoveryLimits, discover_files
from zeroagent.security.workspace import validate_workspace

LANGUAGES = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".sh": "Shell",
    ".bash": "Shell",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
}
KNOWN_FILENAMES = {"Dockerfile": "Shell", "Makefile": "Unknown"}
MANIFESTS = {
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "package.json": "javascript",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(StrictModel):
    finding_type: str
    ecosystem: str | None = None
    evidence: dict[str, str]


class WarningRecord(StrictModel):
    code: str
    message: str
    file: str | None = None


class LanguageStat(StrictModel):
    language: str
    file_count: int
    percentage: float


class Dependency(StrictModel):
    ecosystem: str
    name: str
    declaration: str
    source_file: str
    group: str | None = None


class AnalysisReport(StrictModel):
    schema_version: str = "1.0"
    tool_version: str
    analysis_timestamp: datetime
    workspace_identifier: str
    file_count: int
    directory_count: int
    languages: list[LanguageStat]
    ecosystems: list[str]
    manifests: list[str]
    dependencies: list[Dependency]
    evidence: list[Evidence]
    warnings: list[WarningRecord]
    complete: bool


def detect_language(path: Path) -> str:
    """Return known language name or Unknown from filename and extension."""
    return KNOWN_FILENAMES.get(path.name, LANGUAGES.get(path.suffix.lower(), "Unknown"))


def _parse_pyproject(path: Path) -> tuple[list[Dependency], list[WarningRecord]]:
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        return [], [
            WarningRecord(
                code="malformed_manifest", message=str(error), file="pyproject.toml"
            )
        ]
    project = document.get("project", {})
    if not isinstance(project, dict):
        return [], [
            WarningRecord(
                code="unsupported_manifest",
                message="[project] is not a table",
                file="pyproject.toml",
            )
        ]
    dependencies: list[Dependency] = []
    groups: list[tuple[str | None, object]] = [(None, project.get("dependencies", []))]
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        groups.extend((name, declarations) for name, declarations in optional.items())
    elif optional:
        return [], [
            WarningRecord(
                code="unsupported_manifest",
                message="optional-dependencies is not a table",
                file="pyproject.toml",
            )
        ]
    for group, declarations in groups:
        if not isinstance(declarations, list):
            return [], [
                WarningRecord(
                    code="unsupported_manifest",
                    message="dependencies is not a list",
                    file="pyproject.toml",
                )
            ]
        for declaration in declarations:
            if isinstance(declaration, str):
                name = re.split(r"[<>=!~ ;\[]", declaration, maxsplit=1)[0]
                dependencies.append(
                    Dependency(
                        ecosystem="python",
                        name=name,
                        declaration=declaration,
                        source_file="pyproject.toml",
                        group=group,
                    )
                )
    return dependencies, []


def _parse_requirements(path: Path) -> tuple[list[Dependency], list[WarningRecord]]:
    dependencies: list[Dependency] = []
    warnings: list[WarningRecord] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        return [], [
            WarningRecord(
                code="unreadable_manifest", message=str(error), file="requirements.txt"
            )
        ]
    for number, line in enumerate(lines, start=1):
        declaration = line.split("#", maxsplit=1)[0].strip()
        if not declaration:
            continue
        if declaration.startswith(("-", ".", "/")) or "://" in declaration:
            warnings.append(
                WarningRecord(
                    code="unsupported_requirement",
                    message=f"Unsupported requirement syntax at line {number}",
                    file="requirements.txt",
                )
            )
            continue
        name = re.split(r"[<>=!~ ;\[]", declaration, maxsplit=1)[0]
        dependencies.append(
            Dependency(
                ecosystem="python",
                name=name,
                declaration=declaration,
                source_file="requirements.txt",
            )
        )
    return dependencies, warnings


def _parse_package_json(path: Path) -> tuple[list[Dependency], list[WarningRecord]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return [], [
            WarningRecord(
                code="malformed_manifest", message=str(error), file="package.json"
            )
        ]
    dependencies: list[Dependency] = []
    for group in (
        "dependencies",
        "devDependencies",
        "peerDependencies",
        "optionalDependencies",
    ):
        values = document.get(group, {})
        if not isinstance(values, dict):
            continue
        for name, declaration in values.items():
            if isinstance(name, str) and isinstance(declaration, str):
                dependencies.append(
                    Dependency(
                        ecosystem="javascript",
                        name=name,
                        declaration=declaration,
                        source_file="package.json",
                        group=group,
                    )
                )
    return dependencies, []


def analyze_repository(
    path: Path, limits: DiscoveryLimits | None = None
) -> AnalysisReport:
    """Analyze explicit workspace without executing, importing, or modifying files."""
    workspace = validate_workspace(path)
    discovery = discover_files(workspace, limits or DiscoveryLimits())
    relative_files = [
        file.relative_to(workspace).as_posix() for file in discovery.files
    ]
    languages = Counter(detect_language(file) for file in discovery.files)
    total = len(discovery.files)
    language_stats = [
        LanguageStat(
            language=name,
            file_count=count,
            percentage=round(count / total * 100, 2) if total else 0.0,
        )
        for name, count in sorted(languages.items())
    ]
    manifests = sorted(file for file in relative_files if Path(file).name in MANIFESTS)
    ecosystems = sorted({MANIFESTS[Path(file).name] for file in manifests})
    evidence = [
        Evidence(
            finding_type="language_detection",
            evidence={"file": file, "detector": "extension_detection"},
        )
        for file in relative_files
    ]
    evidence.extend(
        Evidence(
            finding_type="project_manifest",
            ecosystem=MANIFESTS[Path(file).name],
            evidence={"file": file, "detector": "manifest_detection"},
        )
        for file in manifests
    )
    warnings = [
        WarningRecord(code="discovery", message=warning)
        for warning in discovery.warnings
    ]
    dependencies: list[Dependency] = []
    parsers = {
        "pyproject.toml": _parse_pyproject,
        "requirements.txt": _parse_requirements,
        "package.json": _parse_package_json,
    }
    for manifest in manifests:
        parser = parsers.get(Path(manifest).name)
        if parser:
            parsed, parsing_warnings = parser(workspace / manifest)
            dependencies.extend(parsed)
            warnings.extend(parsing_warnings)
    dependencies.sort(key=lambda item: (item.source_file, item.group or "", item.name))
    return AnalysisReport(
        tool_version=__version__,
        analysis_timestamp=datetime.now(UTC),
        workspace_identifier=workspace.name,
        file_count=total,
        directory_count=discovery.directory_count,
        languages=language_stats,
        ecosystems=ecosystems,
        manifests=manifests,
        dependencies=dependencies,
        evidence=evidence,
        warnings=warnings,
        complete=discovery.complete
        and not any(
            w.code in {"malformed_manifest", "unreadable_manifest"} for w in warnings
        ),
    )
