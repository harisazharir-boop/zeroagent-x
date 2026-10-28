"""Engine lifecycle, policy, evidence, and controlled adapter coverage."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from zeroagent.blackbox.storage import LocalStorage
from zeroagent.config import Settings
from zeroagent.execution.adapters import AgentAdapter, OpenCodeAdapter
from zeroagent.execution.coordinator import ExecutionCoordinator, ExecutionError
from zeroagent.execution.models import (
    AdapterCapabilities,
    AdapterResult,
    ExecutionRequest,
    ExecutionState,
)
from zeroagent.execution.registry import AdapterRegistry


class FakeAdapter(AgentAdapter):
    identifier = "opencode"

    def __init__(
        self, *, result: AdapterResult | None = None, delay: float = 0
    ) -> None:
        self.result = result or AdapterResult(exit_code=0, stdout="token=secret-value")
        self.delay = delay
        self.cancelled = False

    def available(self) -> bool:
        return True

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            capabilities=frozenset({"read_only_prompt"}),
            supports_cancellation=True,
            requires_network=False,
        )

    def validate(self, request: ExecutionRequest) -> None:
        del request

    async def execute(self, request: ExecutionRequest) -> AdapterResult:
        del request
        await asyncio.sleep(self.delay)
        return self.result

    async def cancel(self) -> None:
        self.cancelled = True


def settings(**values: object) -> Settings:
    return Settings(agent_execution_enabled=True, opencode_enabled=True, **values)


def request(workspace: Path, **values: object) -> ExecutionRequest:
    payload: dict[str, object] = {
        "workspace": workspace,
        "adapter_id": "opencode",
        "prompt": "harmless task",
        "approved": True,
    }
    payload.update(values)
    return ExecutionRequest(**payload)


@pytest.mark.asyncio
async def test_execution_success_evidence_and_redaction(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path / "records")
    engine = ExecutionCoordinator(
        AdapterRegistry([FakeAdapter()]), settings=settings(), storage=storage
    )
    outcome = await engine.execute(request(tmp_path, record_evidence=True))
    assert outcome.state == ExecutionState.SUCCEEDED
    assert outcome.evidence_id
    assert "secret-value" not in storage.load(outcome.evidence_id).model_dump_json()
    assert outcome.transitions[-1] == ExecutionState.SUCCEEDED


@pytest.mark.asyncio
async def test_policy_approval_workspace_and_unknown_adapter_rejected(
    tmp_path: Path,
) -> None:
    engine = ExecutionCoordinator(AdapterRegistry([FakeAdapter()]), settings=settings())
    denied = await engine.execute(request(tmp_path, approved=False))
    assert denied.state == ExecutionState.FAILED
    assert "approval" in (denied.error_message or "").casefold()
    unknown = await engine.execute(request(tmp_path, adapter_id="other"))
    assert unknown.state == ExecutionState.FAILED
    invalid = await engine.execute(request(tmp_path / "missing"))
    assert invalid.state == ExecutionState.FAILED
    disabled = ExecutionCoordinator(AdapterRegistry([FakeAdapter()]))
    assert (await disabled.execute(request(tmp_path))).state == ExecutionState.FAILED


def test_registry_duplicate_and_unknown_rejected() -> None:
    registry = AdapterRegistry([FakeAdapter()])
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(FakeAdapter())
    with pytest.raises(ValueError, match="Unknown"):
        registry.get("missing")
    assert registry.identifiers() == ("opencode",)


@pytest.mark.asyncio
async def test_timeout_cancellation_and_duplicate_execution(tmp_path: Path) -> None:
    adapter = FakeAdapter(delay=1)
    engine = ExecutionCoordinator(
        AdapterRegistry([adapter]), settings=settings(agent_execution_timeout_seconds=1)
    )
    timed_out = await engine.execute(request(tmp_path, timeout_seconds=1))
    assert timed_out.state == ExecutionState.TIMED_OUT
    assert adapter.cancelled
    running = request(tmp_path, timeout_seconds=5)
    task = asyncio.create_task(engine.execute(running))
    for _ in range(10):
        if running.execution_id in engine._active:
            break
        await asyncio.sleep(0)
    assert await engine.cancel(running.execution_id, "test cancellation")
    cancelled = await task
    assert cancelled.state == ExecutionState.CANCELLED
    assert not await engine.cancel(running.execution_id)
    with pytest.raises(ExecutionError, match="Duplicate"):
        await engine.execute(running)


@pytest.mark.asyncio
async def test_adapter_failure_exception_and_output_limit(tmp_path: Path) -> None:
    result = AdapterResult(exit_code=2, stdout="x" * 5000, error_category="process")
    engine = ExecutionCoordinator(
        AdapterRegistry([FakeAdapter(result=result)]),
        settings=settings(agent_execution_max_output_bytes=1024),
    )
    outcome = await engine.execute(request(tmp_path))
    assert outcome.state == ExecutionState.FAILED
    assert len(outcome.output_summary) == 1024


@pytest.mark.asyncio
async def test_opencode_adapter_missing_executable_and_safe_fake_process(
    tmp_path: Path,
) -> None:
    missing = OpenCodeAdapter(str(tmp_path / "missing"))
    assert not missing.available()
    with pytest.raises(FileNotFoundError):
        missing.validate(request(tmp_path))
    script = tmp_path / "fake_opencode.py"
    script.write_text(
        "import sys; print('ok'); print('err', file=sys.stderr)", encoding="utf-8"
    )
    adapter = OpenCodeAdapter(sys.executable, max_output_bytes=10)
    # Python cannot support documented OpenCode invocation; startup then fails.
    response = await adapter.execute(request(tmp_path))
    assert response.exit_code != 0
    assert len(response.stderr) <= 29
