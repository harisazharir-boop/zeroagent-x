"""Engine lifecycle, policy, evidence, and controlled adapter coverage."""

from __future__ import annotations

import asyncio
import os
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

    async def cancel(self, execution_id: str | None = None) -> None:
        del execution_id
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
def fake_opencode(tmp_path: Path, body: str) -> Path:
    if os.name == "nt":
        script = tmp_path / "fake_opencode.cmd"
        script.write_text(f"@echo off\r\n{body}\r\n", encoding="utf-8")
    else:
        script = tmp_path / "fake_opencode"
        script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        script.chmod(0o700)
    return script


def fake_command(posix: str, windows: str) -> str:
    return windows if os.name == "nt" else posix


def fake_opencode_python(tmp_path: Path, body: str) -> Path:
    program = tmp_path / "fake_opencode.py"
    program.write_text(body, encoding="utf-8")
    if os.name == "nt":
        script = tmp_path / "fake_opencode.cmd"
        script.write_text(
            f'@echo off\r\n"{sys.executable}" "%~dp0{program.name}" %*\r\n',
            encoding="utf-8",
        )
    else:
        script = tmp_path / "fake_opencode"
        script.write_text(
            "#!/bin/sh\n"
            f'exec "{sys.executable}" "$(dirname "$0")/{program.name}" "$@"\n',
            encoding="utf-8",
            newline="\n",
        )
        script.chmod(0o700)
    return script


def output_writer(*, exit_code: int = 0, continuous: bool = False) -> str:
    loop = "while True:" if continuous else "for _ in range(32):"
    ending = "" if continuous else f"\nraise SystemExit({exit_code})"
    return f"""import sys
chunk = b"x" * 4096
{loop}
    sys.stdout.buffer.write(chunk)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(chunk)
    sys.stderr.buffer.flush(){ending}
"""


def continuous_output_opencode(tmp_path: Path) -> Path:
    if os.name == "nt":
        return fake_opencode(
            tmp_path,
            ":loop\r\necho stdout\r\necho stderr 1>&2\r\ngoto loop",
        )
    return fake_opencode_python(tmp_path, output_writer(continuous=True))


def stream_with(*chunks: bytes, eof: bool = True) -> asyncio.StreamReader:
    stream = asyncio.StreamReader()
    for chunk in chunks:
        stream.feed_data(chunk)
    if eof:
        stream.feed_eof()
    return stream


@pytest.mark.asyncio
async def test_opencode_adapter_missing_executable_and_valid_json_stream(
    tmp_path: Path,
) -> None:
    missing = OpenCodeAdapter(str(tmp_path / "missing"))
    assert not missing.available()
    with pytest.raises(FileNotFoundError):
        missing.validate(request(tmp_path))
    script = fake_opencode(
        tmp_path,
        fake_command(
            "printf '%s\\n' "
            '\'{"type":"step_start"}\' '
            '\'{"type":"text","text":"ok"}\'',
            'echo {"type":"step_start"}\r\necho {"type":"text","text":"ok"}',
        ),
    )
    adapter = OpenCodeAdapter(str(script), max_output_bytes=1_024)
    response = await adapter.execute(request(tmp_path))
    assert response.exit_code == 0
    assert response.error_category is None


@pytest.mark.asyncio
async def test_opencode_adapter_rejects_malformed_json_and_cleans_hanging_process(
    tmp_path: Path,
) -> None:
    malformed = OpenCodeAdapter(
        str(
            fake_opencode(
                tmp_path, fake_command("printf 'not json\\n'", "echo not json")
            )
        )
    )
    response = await malformed.execute(request(tmp_path))
    assert response.error_category == "malformed_response"

    hanging = OpenCodeAdapter(
        str(
            fake_opencode(
                tmp_path, fake_command("sleep 60", "timeout /t 60 /nobreak >nul")
            )
        )
    )
    task = asyncio.create_task(hanging.execute(request(tmp_path)))
    await asyncio.sleep(0.05)
    await hanging.cancel()
    response = await task
    assert response.exit_code != 0
    assert response.error_category == "process"


@pytest.mark.asyncio
async def test_opencode_adapter_bounds_oversized_stdout_and_stderr(
    tmp_path: Path,
) -> None:
    limit = 1_024
    adapter = OpenCodeAdapter(
        str(fake_opencode_python(tmp_path, output_writer())), max_output_bytes=limit
    )
    response = await asyncio.wait_for(adapter.execute(request(tmp_path)), timeout=5)
    marker = "\n[output truncated]"
    assert response.exit_code == 0
    assert response.error_category == "malformed_response"
    assert response.stdout.endswith(marker)
    assert response.stderr.endswith(marker)
    assert len(response.stdout.encode("utf-8")) <= limit + len(marker.encode("utf-8"))
    assert len(response.stderr.encode("utf-8")) <= limit + len(marker.encode("utf-8"))
    assert not adapter._processes


@pytest.mark.asyncio
async def test_opencode_adapter_preserves_nonzero_exit_with_bounded_output(
    tmp_path: Path,
) -> None:
    limit = 1_024
    adapter = OpenCodeAdapter(
        str(fake_opencode_python(tmp_path, output_writer(exit_code=7))),
        max_output_bytes=limit,
    )
    response = await asyncio.wait_for(adapter.execute(request(tmp_path)), timeout=5)
    marker = "\n[output truncated]"
    assert response.exit_code == 7
    assert response.error_category == "process"
    assert response.stdout.endswith(marker)
    assert response.stderr.endswith(marker)
    assert len(response.stdout.encode("utf-8")) <= limit + len(marker.encode("utf-8"))
    assert len(response.stderr.encode("utf-8")) <= limit + len(marker.encode("utf-8"))
    assert not adapter._processes


@pytest.mark.asyncio
async def test_opencode_adapter_timeout_cleans_continuous_output(
    tmp_path: Path,
) -> None:
    adapter = OpenCodeAdapter(
        str(continuous_output_opencode(tmp_path)),
        max_output_bytes=1_024,
    )
    engine = ExecutionCoordinator(
        AdapterRegistry([adapter]),
        settings=settings(
            network_enabled=True,
            agent_execution_timeout_seconds=1,
            agent_execution_max_output_bytes=1_024,
        ),
    )
    outcome = await asyncio.wait_for(
        engine.execute(request(tmp_path, timeout_seconds=1)), timeout=5
    )
    assert outcome.state == ExecutionState.TIMED_OUT
    assert outcome.error_category == "timeout"
    assert not adapter._processes


@pytest.mark.asyncio
async def test_opencode_adapter_cancellation_cleans_continuous_output(
    tmp_path: Path,
) -> None:
    adapter = OpenCodeAdapter(
        str(continuous_output_opencode(tmp_path)),
        max_output_bytes=1_024,
    )
    task = asyncio.create_task(adapter.execute(request(tmp_path)))
    for _ in range(100):
        if adapter._processes:
            break
        await asyncio.sleep(0.01)
    assert adapter._processes
    await adapter.cancel()
    response = await asyncio.wait_for(task, timeout=5)
    assert response.exit_code != 0
    assert response.error_category == "process"
    assert not adapter._processes


@pytest.mark.asyncio
async def test_bounded_reader_exact_boundary_and_multiple_chunks(
    tmp_path: Path,
) -> None:
    adapter = OpenCodeAdapter("unused", max_output_bytes=8)
    exact_stdout, exact_truncated = await adapter._drain_bounded(
        stream_with(b"abcd", b"efgh")
    )
    oversized_stderr, oversized_truncated = await adapter._drain_bounded(
        stream_with(b"abcd", b"efgh", b"i")
    )
    assert exact_stdout == b"abcdefgh"
    assert not exact_truncated
    assert adapter._bound(exact_stdout, exact_truncated) == "abcdefgh"
    assert oversized_stderr == b"abcdefgh"
    assert oversized_truncated
    assert adapter._bound(oversized_stderr, oversized_truncated).endswith(
        "\n[output truncated]"
    )


@pytest.mark.asyncio
async def test_bounded_reader_retains_limit_before_stream_exit(tmp_path: Path) -> None:
    del tmp_path
    adapter = OpenCodeAdapter("unused", max_output_bytes=8)
    stream = stream_with(b"x" * 32, eof=False)
    task = asyncio.create_task(adapter._drain_bounded(stream))
    await asyncio.sleep(0)
    assert not task.done()
    stream.feed_eof()
    retained, truncated = await task
    assert retained == b"x" * 8
    assert truncated


@pytest.mark.asyncio
async def test_bounded_reader_clips_single_large_chunk_per_stream(
    tmp_path: Path,
) -> None:
    del tmp_path
    adapter = OpenCodeAdapter("unused", max_output_bytes=8)
    stdout, stderr = await asyncio.gather(
        adapter._drain_bounded(stream_with(b"o" * 64)),
        adapter._drain_bounded(stream_with(b"e" * 64)),
    )
    assert stdout == (b"o" * 8, True)
    assert stderr == (b"e" * 8, True)


@pytest.mark.asyncio
async def test_opencode_adapter_reader_failure_terminates_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = OpenCodeAdapter(
        str(fake_opencode_python(tmp_path, "import time\ntime.sleep(60)"))
    )
    original = adapter._drain_bounded
    failed = False

    async def failing_reader(
        stream: asyncio.StreamReader,
    ) -> tuple[bytes, bool]:
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("reader failed")
        return await original(stream)

    monkeypatch.setattr(adapter, "_drain_bounded", failing_reader)
    with pytest.raises(RuntimeError, match="reader failed"):
        await asyncio.wait_for(adapter.execute(request(tmp_path)), timeout=5)
    assert not adapter._processes


@pytest.mark.asyncio
async def test_settle_readers_cancellation_cancels_pending_reader(
    tmp_path: Path,
) -> None:
    del tmp_path
    adapter = OpenCodeAdapter("unused")
    started = asyncio.Event()

    async def blocked_reader() -> tuple[bytes, bool]:
        started.set()
        await asyncio.Event().wait()
        return b"", False

    reader = asyncio.create_task(blocked_reader())
    cleanup = asyncio.create_task(adapter._settle_readers([reader]))
    await started.wait()
    cleanup.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cleanup
    assert reader.cancelled()
