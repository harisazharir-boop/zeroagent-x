"""Tests for opt-in BlackBox recording and historical replay."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zeroagent.blackbox.recorder import Recorder
from zeroagent.blackbox.redaction import REDACTED, redact_value
from zeroagent.blackbox.replay import replay
from zeroagent.blackbox.storage import LocalStorage, StorageError
from zeroagent.cli import app

runner = CliRunner()


def _record() -> tuple[Recorder, object]:
    recorder = Recorder("Analyze repository password=hunter2")
    recorder.emit("task_classified", {"api_key": "AKIAABCDEFGHIJKLMNOP"})
    return recorder, recorder.build(
        status="SUCCEEDED", task_category="repository_analysis"
    )


def test_redaction_removes_synthetic_secrets_and_environment_values() -> None:
    sanitized = redact_value(
        {
            "password": "hunter2",
            "authorization": "Bearer secret-token",
            "message": "api_key=synthetic-secret",
        }
    )
    assert sanitized["password"] == REDACTED
    assert sanitized["authorization"] == REDACTED
    assert "synthetic-secret" not in sanitized["message"]


def test_storage_save_load_history_and_replay(tmp_path: Path) -> None:
    recorder, record = _record()
    storage = LocalStorage(tmp_path, max_records=2)
    storage.save(record)
    loaded = storage.load(record.execution_id)

    assert loaded.execution_id == record.execution_id
    assert loaded.task_description != "Analyze repository password=hunter2"
    assert [event.sequence for event in replay(loaded).events] == [1, 2, 3]
    assert storage.list_records(1)[0].execution_id == record.execution_id
    with pytest.raises(StorageError, match="already exists"):
        storage.save(record)


def test_recorder_generates_unique_ids_and_retention_is_bounded(tmp_path: Path) -> None:
    first_recorder, first = _record()
    second_recorder, second = _record()
    storage = LocalStorage(tmp_path, max_records=1)
    storage.save(first)
    storage.save(second)

    assert first_recorder.execution_id != second_recorder.execution_id
    assert [record.execution_id for record in storage.list_records(10)] == [
        second.execution_id
    ]


@pytest.mark.parametrize("execution_id", ["../bad", "C:\\bad", "short", "a" * 33])
def test_storage_rejects_invalid_ids(tmp_path: Path, execution_id: str) -> None:
    with pytest.raises(StorageError, match="Invalid"):
        LocalStorage(tmp_path).load(execution_id)


def test_storage_rejects_corrupted_and_oversized_records(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path, max_record_bytes=50)
    _, record = _record()
    with pytest.raises(StorageError, match="size"):
        storage.save(record)
    record_id = "a" * 32
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / f"{record_id}.json").write_text("{")
    with pytest.raises(StorageError, match="Cannot read"):
        LocalStorage(tmp_path).load(record_id)


def test_storage_rejects_oversized_record_before_read(tmp_path: Path) -> None:
    record_id = "b" * 32
    path = tmp_path / f"{record_id}.json"
    path.write_text("x" * 100)
    with pytest.raises(StorageError, match="size limit"):
        LocalStorage(tmp_path, max_record_bytes=50).load(record_id)


def test_cli_record_history_inspect_and_replay(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "module.py").write_text("pass\n")
    storage = tmp_path / "records"
    run = runner.invoke(
        app,
        [
            "run",
            "Analyze this repository",
            "--workspace",
            str(workspace),
            "--verify",
            "--record",
            "--storage-dir",
            str(storage),
            "--format",
            "json",
        ],
    )
    assert run.exit_code == 0
    execution_id = json.loads(run.output)["execution_id"]
    history = runner.invoke(
        app, ["history", "--storage-dir", str(storage), "--format", "json"]
    )
    inspected = runner.invoke(
        app, ["inspect", execution_id, "--storage-dir", str(storage)]
    )
    replayed = runner.invoke(
        app, ["replay", execution_id, "--storage-dir", str(storage), "--format", "json"]
    )

    assert json.loads(history.output)[0]["execution_id"] == execution_id
    assert inspected.exit_code == 0
    assert json.loads(replayed.output)["execution_id"] == execution_id
    assert len(list(storage.glob("*.json"))) == 1


def test_run_without_record_does_not_create_configured_storage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    storage = tmp_path / "records"
    result = runner.invoke(
        app,
        [
            "run",
            "Analyze this repository",
            "--workspace",
            str(workspace),
            "--storage-dir",
            str(storage),
        ],
    )
    assert result.exit_code == 0
    assert not storage.exists()
