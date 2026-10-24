"""Safe local JSON storage for sanitized BlackBox records."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from zeroagent.blackbox.models import ExecutionRecord

RECORD_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class StorageError(RuntimeError):
    """Raised for safe storage and record-loading failures."""


def default_storage_dir() -> Path:
    """Return user data location without writing inside analyzed workspace."""
    if os.name == "nt":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            / "ZEROAGENT X"
            / "blackbox"
        )
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / "zeroagent"
        / "blackbox"
    )


class LocalStorage:
    """Versioned JSON-record storage with ID validation and bounded retention."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        max_records: int = 100,
        max_record_bytes: int = 1_000_000,
        max_age_days: int | None = 30,
    ) -> None:
        self.root = root or default_storage_dir()
        self.max_records = max_records
        self.max_record_bytes = max_record_bytes
        self.max_age_days = max_age_days

    def _ensure_root(self) -> None:
        if self.root.exists() and self.root.is_symlink():
            raise StorageError("BlackBox storage directory must not be a symbolic link")
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                self.root.chmod(0o700)
        except OSError as error:
            raise StorageError(f"Cannot prepare BlackBox storage: {error}") from error

    def _path(self, execution_id: str) -> Path:
        if not RECORD_ID_PATTERN.fullmatch(execution_id):
            raise StorageError("Invalid execution ID")
        return self.root / f"{execution_id}.json"

    def _record_paths(self) -> list[Path]:
        if not self.root.exists():
            return []
        return sorted(
            (
                path
                for path in self.root.glob("*.json")
                if path.is_file() and not path.is_symlink()
            ),
            key=lambda path: (path.stat().st_mtime, path.name),
            reverse=True,
        )

    def save(self, record: ExecutionRecord) -> None:
        self._ensure_root()
        target = self._path(record.execution_id)
        if target.exists() or target.is_symlink():
            raise StorageError("Execution record already exists")
        data = record.model_dump_json(indent=2).encode("utf-8") + b"\n"
        if len(data) > self.max_record_bytes:
            raise StorageError("Execution record exceeds configured size limit")
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".record-", dir=self.root
            )
            with os.fdopen(descriptor, "wb") as temporary:
                temporary.write(data)
                temporary.flush()
                os.fsync(temporary.fileno())
            if os.name != "nt":
                os.chmod(temporary_name, 0o600)
            os.link(temporary_name, target)
            os.unlink(temporary_name)
            self.cleanup(keep_count=self.max_records)
        except FileExistsError as error:
            raise StorageError("Execution record already exists") from error
        except OSError as error:
            raise StorageError(f"Cannot persist BlackBox record: {error}") from error
        finally:
            if "temporary_name" in locals() and os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def load(self, execution_id: str) -> ExecutionRecord:
        path = self._path(execution_id)
        try:
            metadata = path.lstat()
        except FileNotFoundError as error:
            raise StorageError("Execution record does not exist") from error
        if path.is_symlink() or not path.is_file():
            raise StorageError("Execution record does not exist")
        if metadata.st_size > self.max_record_bytes:
            raise StorageError("Execution record exceeds configured size limit")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            record = ExecutionRecord.model_validate(data)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise StorageError(f"Cannot read execution record: {error}") from error
        if record.schema_version != "1.0":
            raise StorageError("Unsupported execution record schema")
        return record

    def list_records(self, limit: int = 20) -> list[ExecutionRecord]:
        records: list[ExecutionRecord] = []
        for path in self._record_paths():
            if len(records) >= limit:
                break
            try:
                records.append(self.load(path.stem))
            except StorageError:
                continue
        return sorted(records, key=lambda record: record.started_at, reverse=True)

    def cleanup(self, *, keep_count: int | None = None) -> list[str]:
        """Remove only regular record files inside storage per retention limits."""
        self._ensure_root()
        paths = self._record_paths()
        cutoff = (
            datetime.now(UTC) - timedelta(days=self.max_age_days)
            if self.max_age_days is not None
            else None
        )
        removed: list[str] = []
        for index, path in enumerate(paths):
            remove_for_count = keep_count is not None and index >= keep_count
            remove_for_age = (
                cutoff is not None
                and datetime.fromtimestamp(path.stat().st_mtime, UTC) < cutoff
            )
            if remove_for_count or remove_for_age:
                try:
                    path.unlink()
                    removed.append(path.stem)
                except OSError as error:
                    raise StorageError(
                        f"Cannot clean BlackBox record: {error}"
                    ) from error
        return removed
