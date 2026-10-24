"""Read-only history helpers."""

from zeroagent.blackbox.models import ExecutionRecord
from zeroagent.blackbox.storage import LocalStorage


def history(storage: LocalStorage, limit: int) -> list[ExecutionRecord]:
    """Return bounded newest-first local records without executing anything."""
    return storage.list_records(limit)
