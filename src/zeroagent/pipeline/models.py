"""Bounded in-memory records for controlled pipeline runs."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class PipelineState(StrEnum):
    OFF = "OFF"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PipelineModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StageEvidence(PipelineModel):
    name: str = Field(max_length=40)
    outcome: str = Field(max_length=20)
    detail: str = Field(default="", max_length=400)
    started_at: datetime
    ended_at: datetime | None = None
    operation_digest: str | None = Field(default=None, max_length=64)
    approval_digest: str | None = Field(default=None, max_length=64)
    error_summary: str = Field(default="", max_length=400)


class PipelineRun(PipelineModel):
    run_id: str
    task_summary: str = Field(max_length=400)
    workspace_identifier: str = Field(max_length=200)
    state: PipelineState
    active_stage: str | None = None
    awaiting: str | None = None
    stages: list[StageEvidence] = Field(default_factory=list, max_length=20)
    started_at: datetime
    ended_at: datetime | None = None
    error_summary: str = Field(default="", max_length=400)
    cancellation_requested: bool = False


class PipelineReport(PipelineModel):
    """Bounded terminal account of actual controlled pipeline work."""

    run: PipelineRun
    apply_status: str = Field(default="NOT_EXECUTED", max_length=32)
    test_status: str = Field(default="NOT_EXECUTED", max_length=32)
    proof_status: str = Field(default="INCOMPLETE", max_length=32)
    skipped_stages: list[str] = Field(default_factory=list, max_length=4)
    cancellation_status: str = Field(default="NOT_REQUESTED", max_length=32)
    limitation: str = Field(default="", max_length=400)


def new_run(task: str, workspace_identifier: str) -> PipelineRun:
    return PipelineRun(
        run_id=uuid4().hex,
        task_summary=" ".join(task.split())[:400],
        workspace_identifier=workspace_identifier,
        state=PipelineState.PREPARING,
        started_at=datetime.now(UTC),
    )
