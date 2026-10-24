"""In-memory execution event recorder and sanitized record builder."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from zeroagent import __version__
from zeroagent.blackbox.models import ExecutionEvent, ExecutionRecord
from zeroagent.blackbox.redaction import redact_text, redact_value


class Recorder:
    """Records real lifecycle calls before optional persistence."""

    def __init__(self, task: str) -> None:
        self.execution_id = uuid4().hex
        self.started_at = datetime.now(UTC)
        self.task = redact_text(task)
        self.events: list[ExecutionEvent] = []
        self.emit("execution_started")

    def emit(self, event_type: str, details: dict[str, object] | None = None) -> None:
        self.events.append(
            ExecutionEvent(
                sequence=len(self.events) + 1,
                event_type=event_type,
                timestamp=datetime.now(UTC),
                details=redact_value(details or {}),
            )
        )

    def build(
        self,
        *,
        status: str,
        capability_identifier: str | None = None,
        task_category: str | None = None,
        routing: dict[str, object] | None = None,
        result_summary: dict[str, object] | None = None,
        proof_summary: dict[str, object] | None = None,
        error: str | None = None,
        complete: bool = True,
    ) -> ExecutionRecord:
        self.emit("execution_finished", {"status": status})
        return ExecutionRecord(
            execution_id=self.execution_id,
            tool_version=__version__,
            started_at=self.started_at,
            ended_at=datetime.now(UTC),
            status=status,
            capability_identifier=capability_identifier,
            task_category=task_category,
            task_description=self.task,
            routing=redact_value(routing) if routing else None,
            events=self.events,
            result_summary=redact_value(result_summary) if result_summary else None,
            proof_summary=redact_value(proof_summary) if proof_summary else None,
            error=redact_text(error) if error else None,
            complete=complete,
            recording_limitations=[
                "Best-effort redaction; records are not tamper-proof.",
                "Historical replay displays stored data and never reruns capabilities.",
            ],
        )
