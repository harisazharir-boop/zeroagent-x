"""Tests for CLI behavior."""

import json
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from zeroagent import __version__
from zeroagent.cli import app

runner = CliRunner()


def test_help_is_available() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "ZEROAGENT X" in result.output
    assert "doctor" in result.output


def test_bare_cli_in_noninteractive_mode_shows_help() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Usage: zeroagent" in result.output
    assert "tui" in result.output


def test_version_is_available() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_reports_runtime_details(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert __version__ in result.output
    assert "Python" in result.output
    assert "Platform" in result.output
    assert "Current directory" in result.output
    assert "disabled" in result.output


def test_module_entry_point_runs() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "zeroagent", "--version"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == __version__


def test_analyze_json_and_output_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    destination = tmp_path / "report.json"

    result = runner.invoke(
        app,
        ["analyze", str(tmp_path), "--format", "json", "--output", str(destination)],
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["workspace_identifier"] == tmp_path.name
    assert json.loads(destination.read_text())["manifests"] == ["pyproject.toml"]


def test_analyze_rejects_missing_workspace(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path / "missing")])

    assert result.exit_code == 2
    assert "Analysis failed" in result.output


def test_analyze_protects_existing_output(tmp_path: Path) -> None:
    destination = tmp_path / "report.json"
    destination.write_text("existing")

    result = runner.invoke(
        app, ["analyze", str(tmp_path), "--output", str(destination)]
    )

    assert result.exit_code == 2
    assert destination.read_text() == "existing"


def test_route_json_does_not_execute_handler() -> None:
    result = runner.invoke(
        app, ["route", "Analyze this repository", "--format", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["selected_capability"] == "repository_analyzer"
    assert payload["execution_performed"] is False


def test_run_executes_repository_analysis(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("pass\n")

    result = runner.invoke(
        app,
        [
            "run",
            "Analyze this repository",
            "--workspace",
            str(tmp_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["routing"]["execution_performed"] is True
    assert payload["result"]["file_count"] == 1


def test_run_rejects_unknown_task_and_missing_workspace(tmp_path: Path) -> None:
    unknown = runner.invoke(app, ["run", "Deploy this application"])
    missing = runner.invoke(app, ["run", "Analyze this repository"])

    assert unknown.exit_code == 2
    assert missing.exit_code == 2
    assert "Run failed" in unknown.output
    assert "--workspace" in missing.output


def test_run_verify_returns_actual_proof_json(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("pass\n")
    result = runner.invoke(
        app,
        [
            "run",
            "Analyze this repository",
            "--workspace",
            str(tmp_path),
            "--verify",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["proof"]["overall_status"] == "VERIFIED"
    assert payload["routing"]["execution_performed"] is True
