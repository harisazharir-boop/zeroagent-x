"""Strict execution contracts independent of any agent implementation."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExecutionState(str, Enum):  # noqa: UP042
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


TERMINAL_STATES = frozenset(
    {
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
        ExecutionState.TIMED_OUT,
    }
)


class ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExecutionRequest(ExecutionModel):
    """One explicit agent request. No implicit workspace or adapter selection."""

    execution_id: str = Field(default_factory=lambda: uuid4().hex)
    adapter_id: str
    workspace: Path
    prompt: str = Field(min_length=1, max_length=8_000)
    capability: str = "read_only_prompt"
    approval_required: bool = True
    approved: bool = False
    record_evidence: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=600)

    @field_validator("adapter_id", "capability")
    @classmethod
    def nonempty_identifier(cls, value: str) -> str:
        if not value or value.strip() != value:
            raise ValueError(
                "identifier must be non-empty and have no surrounding whitespace"
            )
        return value


class AdapterCapabilities(ExecutionModel):
    capabilities: frozenset[str] = frozenset()
    supports_cancellation: bool = False
    requires_network: bool = False


class AdapterResult(ExecutionModel):
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error_category: (
        Literal[
            "missing_executable",
            "unsupported_invocation",
            "startup",
            "adapter",
            "process",
        ]
        | None
    ) = None
    error_message: str | None = None


class ExecutionResult(ExecutionModel):
    execution_id: str
    adapter_id: str
    state: ExecutionState
    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(ge=0)
    exit_code: int | None = None
    error_category: str | None = None
    error_message: str | None = None
    output_summary: str = ""
    evidence_id: str | None = None
    cancellation_reason: str | None = None
    transitions: tuple[ExecutionState, ...]
