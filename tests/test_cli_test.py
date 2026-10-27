"""Tests for zeroagent test CLI subcommands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from zeroagent.cli import app

runner = CliRunner()


def test_cli_test_runners() -> None:
    res = runner.invoke(app, ["test", "runners", "--format", "json"])
    assert res.exit_code == 0
    runners = json.loads(res.output)
    assert "pytest" in runners


def test_cli_test_create_and_validate(tmp_path: Path) -> None:
    res = runner.invoke(
        app,
        [
            "test",
            "create",
            "--workspace",
            str(tmp_path),
            "--runner",
            "pytest",
            "--args",
            "-q -k test_sample",
            "--format",
            "json",
        ],
    )
    assert res.exit_code == 0
    spec_data = json.loads(res.output)
    assert spec_data["runner"] == "pytest"
    assert spec_data["arguments"] == ["-q", "-k", "test_sample"]
    assert len(spec_data["digest"]) == 64

    # Save to file and validate
    spec_file = tmp_path / "test_spec.json"
    spec_file.write_text(json.dumps(spec_data))

    val_res = runner.invoke(
        app,
        [
            "test",
            "validate",
            str(spec_file),
            "--workspace",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    assert val_res.exit_code == 0
    val_data = json.loads(val_res.output)
    assert val_data["digest"] == spec_data["digest"]


def test_cli_test_preview(tmp_path: Path) -> None:
    create_res = runner.invoke(
        app,
        [
            "test",
            "create",
            "--workspace",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    spec_data = json.loads(create_res.output)
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec_data))

    prev_res = runner.invoke(
        app,
        [
            "test",
            "preview",
            str(spec_file),
            "--workspace",
            str(tmp_path),
        ],
    )
    assert prev_res.exit_code == 0
    assert spec_data["digest"] in prev_res.output
    assert "pytest" in prev_res.output
    assert "Notice: Pytest executes repository code" in prev_res.output


def test_cli_test_run_rejection_without_exact_digest(tmp_path: Path) -> None:
    create_res = runner.invoke(
        app,
        [
            "test",
            "create",
            "--workspace",
            str(tmp_path),
            "--format",
            "json",
        ],
    )
    spec_data = json.loads(create_res.output)
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec_data))

    run_res = runner.invoke(
        app,
        [
            "test",
            "run",
            str(spec_file),
            "--workspace",
            str(tmp_path),
            "--approve-digest",
            "0" * 64,
        ],
    )
    assert run_res.exit_code == 2
    assert "Approval digest does not match" in run_res.output


def test_cli_test_run_approved_with_audit_record(tmp_path: Path) -> None:
    test_file = tmp_path / "test_ok.py"
    test_file.write_text("def test_cli_ok(): assert 1 == 1\n")

    create_res = runner.invoke(
        app,
        [
            "test",
            "create",
            "--workspace",
            str(tmp_path),
            "--args",
            "test_ok.py",
            "--format",
            "json",
        ],
    )
    spec_data = json.loads(create_res.output)
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec_data))

    storage_dir = tmp_path / "bb_storage"
    run_res = runner.invoke(
        app,
        [
            "test",
            "run",
            str(spec_file),
            "--workspace",
            str(tmp_path),
            "--approve-digest",
            spec_data["digest"],
            "--record",
            "--storage-dir",
            str(storage_dir),
        ],
    )
    assert run_res.exit_code == 0
    data = json.loads(run_res.output)
    assert data["result"]["status"] == "PASSED"
    assert data["proof"]["overall_status"] == "INCOMPLETE"
    assert data["audit"] == "recorded"

    # Verify audit record exists and doesn't store raw test output
    records = list(storage_dir.glob("*.json"))
    assert len(records) == 1
    raw = records[0].read_text()
    assert spec_data["digest"] in raw
    assert "def test_cli_ok" not in raw
