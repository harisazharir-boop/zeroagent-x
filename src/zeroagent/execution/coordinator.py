"""Policy-owned execution lifecycle coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic

from zeroagent.blackbox.recorder import Recorder
from zeroagent.blackbox.storage import LocalStorage
from zeroagent.config import Settings, load_settings
from zeroagent.execution.models import (
    TERMINAL_STATES,
    AdapterResult,
    ExecutionRequest,
    ExecutionResult,
    ExecutionState,
)
from zeroagent.execution.registry import AdapterRegistry
from zeroagent.security.workspace import WorkspaceError, validate_workspace


class ExecutionError(RuntimeError):
    pass


_TRANSITIONS = {
    ExecutionState.CREATED: {ExecutionState.VALIDATING, ExecutionState.CANCELLED},
    ExecutionState.VALIDATING: {
        ExecutionState.AWAITING_APPROVAL,
        ExecutionState.READY,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.AWAITING_APPROVAL: {
        ExecutionState.READY,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.READY: {ExecutionState.RUNNING, ExecutionState.CANCELLED},
    ExecutionState.RUNNING: {
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
        ExecutionState.TIMED_OUT,
    },
}


class ExecutionCoordinator:
    def __init__(
        self,
        registry: AdapterRegistry,
        *,
        settings: Settings | None = None,
        storage: LocalStorage | None = None,
        approval_authorizer: Callable[[ExecutionRequest], bool] | None = None,
    ) -> None:
        self.registry = registry
        self.settings = settings or load_settings()
        self.storage = storage
        self.approval_authorizer = approval_authorizer
        self._active: dict[str, object] = {}
        self._states: dict[str, list[ExecutionState]] = {}
        self._cancelled: dict[str, str] = {}

    def state(self, execution_id: str) -> ExecutionState:
        return self._states[execution_id][-1]

    def _move(self, execution_id: str, state: ExecutionState) -> None:
        current = self.state(execution_id)
        if state not in _TRANSITIONS.get(current, set()):
            raise ExecutionError(f"Invalid lifecycle transition: {current} -> {state}")
        self._states[execution_id].append(state)

    async def cancel(
        self, execution_id: str, reason: str = "Cancellation requested"
    ) -> bool:
        if (
            execution_id not in self._states
            or self.state(execution_id) in TERMINAL_STATES
        ):
            return False
        self._cancelled[execution_id] = reason
        adapter = self._active.get(execution_id)
        if adapter is not None:
            await adapter.cancel(execution_id)  # type: ignore[union-attr]
        if self.state(execution_id) not in TERMINAL_STATES:
            self._move(execution_id, ExecutionState.CANCELLED)
        return True

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        if request.execution_id in self._states:
            raise ExecutionError("Duplicate execution ID")
        self._states[request.execution_id] = [ExecutionState.CREATED]
        started = datetime.now(UTC)
        clock = monotonic()
        recorder = Recorder(request.prompt)
        adapter = None
        result = AdapterResult()
        error_category = error_message = None
        try:
            self._move(request.execution_id, ExecutionState.VALIDATING)
            workspace = validate_workspace(request.workspace)
            if (
                not self.settings.agent_execution_enabled
                or not self.settings.opencode_enabled
            ):
                raise ExecutionError("Agent execution is disabled by policy")
            adapter = self.registry.get(request.adapter_id)
            if (
                adapter.capabilities().requires_network
                and not self.settings.network_enabled
            ):
                raise ExecutionError(
                    "Adapter requires network but network policy is disabled"
                )
            adapter.validate(request.model_copy(update={"workspace": workspace}))
            recorder.emit(
                "policy_checked",
                {"adapter": request.adapter_id, "approved": request.approved},
            )
            approved = request.approved
            if request.approval_required and self.approval_authorizer is not None:
                approved = self.approval_authorizer(request)
            if request.approval_required and not approved:
                self._move(request.execution_id, ExecutionState.AWAITING_APPROVAL)
                raise ExecutionError("Explicit approval is required")
            self._move(request.execution_id, ExecutionState.READY)
            if request.execution_id in self._cancelled:
                self._move(request.execution_id, ExecutionState.CANCELLED)
            else:
                self._move(request.execution_id, ExecutionState.RUNNING)
                self._active[request.execution_id] = adapter
                timeout = (
                    request.timeout_seconds
                    or self.settings.agent_execution_timeout_seconds
                )
                try:
                    result = await asyncio.wait_for(
                        adapter.execute(
                            request.model_copy(update={"workspace": workspace})
                        ),
                        timeout,
                    )
                except TimeoutError:
                    await adapter.cancel(request.execution_id)
                    self._move(request.execution_id, ExecutionState.TIMED_OUT)
                    error_category = "timeout"
                    error_message = f"Execution exceeded {timeout} seconds"
                else:
                    if request.execution_id in self._cancelled:
                        self._move(request.execution_id, ExecutionState.CANCELLED)
                    elif result.error_category or result.exit_code != 0:
                        self._move(request.execution_id, ExecutionState.FAILED)
                    else:
                        self._move(request.execution_id, ExecutionState.SUCCEEDED)
        except (ExecutionError, WorkspaceError, ValueError, FileNotFoundError) as error:
            error_category = (
                "policy" if isinstance(error, ExecutionError) else "validation"
            )
            error_message = str(error)
            if self.state(request.execution_id) not in TERMINAL_STATES:
                self._move(
                    request.execution_id,
                    ExecutionState.CANCELLED
                    if request.execution_id in self._cancelled
                    else ExecutionState.FAILED,
                )
        except Exception as error:
            error_category = "adapter_exception"
            error_message = str(error)
            if self.state(request.execution_id) not in TERMINAL_STATES:
                self._move(request.execution_id, ExecutionState.FAILED)
        finally:
            self._active.pop(request.execution_id, None)
        finished = datetime.now(UTC)
        state = self.state(request.execution_id)
        summary = (result.stdout + ("\n" + result.stderr if result.stderr else ""))[
            : self.settings.agent_execution_max_output_bytes
        ]
        evidence_id = None
        if request.record_evidence and self.storage:
            record = recorder.build(
                status="SUCCEEDED" if state == ExecutionState.SUCCEEDED else "FAILED",
                capability_identifier=request.adapter_id,
                result_summary={
                    "state": state.value,
                    "exit_code": result.exit_code,
                    "output_summary": summary,
                },
                error=error_message or result.error_message,
                complete=True,
            )
            self.storage.save(record)
            evidence_id = record.execution_id
        return ExecutionResult(
            execution_id=request.execution_id,
            adapter_id=request.adapter_id,
            state=state,
            started_at=started,
            finished_at=finished,
            duration_seconds=monotonic() - clock,
            exit_code=result.exit_code,
            error_category=error_category or result.error_category,
            error_message=error_message or result.error_message,
            output_summary=summary,
            evidence_id=evidence_id,
            cancellation_reason=self._cancelled.get(request.execution_id),
            transitions=tuple(self._states[request.execution_id]),
        )
