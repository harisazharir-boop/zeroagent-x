"""Agent adapter contract and local OpenCode subprocess adapter."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
from abc import ABC, abstractmethod
from pathlib import Path

from zeroagent.execution.models import (
    AdapterCapabilities,
    AdapterResult,
    ExecutionRequest,
)


class AgentAdapter(ABC):
    """Adapter cannot make policy decisions; coordinator always owns those."""

    identifier: str

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def capabilities(self) -> AdapterCapabilities: ...

    @abstractmethod
    def validate(self, request: ExecutionRequest) -> None: ...

    @abstractmethod
    async def execute(self, request: ExecutionRequest) -> AdapterResult: ...

    @abstractmethod
    async def cancel(self, execution_id: str | None = None) -> None: ...


class OpenCodeAdapter(AgentAdapter):
    """OpenCode `run --format json` adapter without shell interpolation or --auto."""

    identifier = "opencode"

    def __init__(
        self, executable: str = "opencode", *, max_output_bytes: int = 64_000
    ) -> None:
        self.executable = executable
        self.max_output_bytes = max_output_bytes
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def _path(self) -> str | None:
        if Path(self.executable).is_absolute():
            return self.executable if Path(self.executable).is_file() else None
        return shutil.which(self.executable)

    def available(self) -> bool:
        return self._path() is not None

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            capabilities=frozenset({"read_only_prompt"}),
            supports_cancellation=True,
            requires_network=True,
        )

    def validate(self, request: ExecutionRequest) -> None:
        if request.capability not in self.capabilities().capabilities:
            raise ValueError("OpenCode capability is unsupported")
        if not self.available():
            raise FileNotFoundError("Configured OpenCode executable is unavailable")
        if "\x00" in request.prompt:
            raise ValueError("OpenCode prompt contains NUL")

    async def execute(self, request: ExecutionRequest) -> AdapterResult:
        executable = self._path()
        if executable is None:
            return AdapterResult(
                error_category="missing_executable",
                error_message="OpenCode unavailable",
            )
        # OpenCode v2.1.4 help confirms `run --standalone --format json <message...>`.
        # Standalone avoids an uncontrolled shared background server/session.
        # `cwd` pins OpenCode process to explicitly validated workspace.
        args = [
            executable,
            "run",
            "--standalone",
            "--format",
            "json",
            request.prompt,
        ]
        kwargs: dict[str, object] = {
            "cwd": request.workspace,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(
                __import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0
            )
        else:
            kwargs["start_new_session"] = True
        try:
            process = await asyncio.create_subprocess_exec(*args, **kwargs)
            self._processes[request.execution_id] = process
            stdout, stderr = await self._capture_output(process)
            bounded_stdout = self._bound(*stdout)
            bounded_stderr = self._bound(*stderr)
            if process.returncode != 0:
                return AdapterResult(
                    exit_code=process.returncode,
                    stdout=bounded_stdout,
                    stderr=bounded_stderr,
                    error_category="process",
                    error_message="OpenCode exited unsuccessfully",
                )
            if not self._is_json_event_stream(bounded_stdout):
                return AdapterResult(
                    exit_code=process.returncode,
                    stdout=bounded_stdout,
                    stderr=bounded_stderr,
                    error_category="malformed_response",
                    error_message="OpenCode returned no valid JSON events",
                )
            return AdapterResult(
                exit_code=process.returncode,
                stdout=bounded_stdout,
                stderr=bounded_stderr,
            )
        except OSError as error:
            return AdapterResult(error_category="startup", error_message=str(error))
        except asyncio.CancelledError:
            await self.cancel(request.execution_id)
            raise
        finally:
            self._processes.pop(request.execution_id, None)

    async def _capture_output(
        self, process: asyncio.subprocess.Process
    ) -> tuple[tuple[bytes, bool], tuple[bytes, bool]]:
        """Drain both pipes while retaining at most one configured limit per stream."""
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(self._drain_bounded(process.stdout))
        stderr_task = asyncio.create_task(self._drain_bounded(process.stderr))
        wait_task = asyncio.create_task(process.wait())
        readers = (stdout_task, stderr_task)
        try:
            done, _ = await asyncio.wait(
                {wait_task, *readers}, return_when=asyncio.FIRST_EXCEPTION
            )
            for task in done:
                if task in readers and not task.cancelled():
                    exception = task.exception()
                    if exception is not None:
                        await self._cancel_process(process)
                        raise exception
            await wait_task
            stdout, stderr = await asyncio.gather(*readers)
            return stdout, stderr
        except asyncio.CancelledError:
            await self._cleanup_capture(process, readers, wait_task)
            raise
        except Exception:
            await self._cleanup_capture(process, readers, wait_task)
            raise
        finally:
            if process.returncode is None or any(not task.done() for task in readers):
                await self._cleanup_capture(process, readers, wait_task)

    async def _drain_bounded(self, stream: asyncio.StreamReader) -> tuple[bytes, bool]:
        retained = bytearray()
        truncated = False
        while chunk := await stream.read(64 * 1024):
            remaining = self.max_output_bytes - len(retained)
            if remaining > 0:
                retained.extend(chunk[:remaining])
            if len(chunk) > max(remaining, 0):
                truncated = True
        return bytes(retained), truncated

    async def _cleanup_capture(
        self,
        process: asyncio.subprocess.Process,
        readers: tuple[asyncio.Task[tuple[bytes, bool]], ...],
        wait_task: asyncio.Task[int],
    ) -> None:
        """Terminate process, then settle readers without masking caller failure."""
        if process.returncode is None:
            await self._cancel_process(process)
        pending = [task for task in readers if not task.done()]
        if pending:
            await self._settle_readers(pending)
        if not wait_task.done():
            wait_task.cancel()
            await asyncio.gather(wait_task, return_exceptions=True)

    async def _settle_readers(
        self, readers: list[asyncio.Task[tuple[bytes, bool]]]
    ) -> None:
        try:
            await asyncio.wait_for(
                asyncio.gather(*readers, return_exceptions=True), timeout=3
            )
        except TimeoutError:
            for task in readers:
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*readers, return_exceptions=True), timeout=3
                )
            except TimeoutError:
                return
        except asyncio.CancelledError:
            for task in readers:
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(*readers, return_exceptions=True), timeout=3
                )
            except TimeoutError:
                pass
            raise

    @staticmethod
    def _bound(data: bytes, truncated: bool) -> str:
        suffix = "\n[output truncated]" if truncated else ""
        return data.decode("utf-8", errors="replace") + suffix

    @staticmethod
    def _is_json_event_stream(output: str) -> bool:
        """Require nonempty JSON-object lines from documented `--format json` mode."""
        lines = output.splitlines()
        if not lines or output.endswith("[output truncated]"):
            return False
        try:
            return all(isinstance(json.loads(line), dict) for line in lines)
        except json.JSONDecodeError:
            return False

    async def cancel(self, execution_id: str | None = None) -> None:
        processes = (
            [self._processes[execution_id]]
            if execution_id is not None and execution_id in self._processes
            else list(self._processes.values())
            if execution_id is None
            else []
        )
        for process in processes:
            await self._cancel_process(process)

    async def _cancel_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            process.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except TimeoutError:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    return
            await process.wait()
