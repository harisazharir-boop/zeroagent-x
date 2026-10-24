"""Historical-only replay helpers."""

from zeroagent.blackbox.models import ExecutionRecord


def replay(record: ExecutionRecord) -> ExecutionRecord:
    """Return stored record unchanged; never execute handlers or access workspace."""
    return record
