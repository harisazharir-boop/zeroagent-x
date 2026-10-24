"""Typed, sanitized local execution-history records."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ExecutionStatus = Literal["SUCCEEDED", "FAILED"]


class BlackBoxModel(BaseModel):
    """Strict immutable base for persisted BlackBox data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ExecutionEvent(BlackBoxModel):
    sequence: int
    event_type: Literal[
        "execution_started",
        "task_classified",
        "capability_selected",
        "policy_checked",
        "capability_started",
        "capability_completed",
        "verification_started",
        "verification_completed",
        "execution_failed",
        "execution_finished",
        "edit_application",
    ]
    timestamp: datetime
    details: dict[str, object] = {}


class ExecutionRecord(BlackBoxModel):
    schema_version: str = "1.0"
    execution_id: str
    tool_version: str
    started_at: datetime
    ended_at: datetime | None = None
    status: ExecutionStatus
    capability_identifier: str | None = None
    task_category: str | None = None
    task_description: str
    routing: dict[str, object] | None = None
    events: list[ExecutionEvent]
    result_summary: dict[str, object] | None = None
    proof_summary: dict[str, object] | None = None
    error: str | None = None
    complete: bool
    recording_limitations: list[str]
