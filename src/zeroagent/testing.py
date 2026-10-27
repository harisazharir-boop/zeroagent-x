"""Controlled, allowlisted, approval-bound local test execution subsystem."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from zeroagent.security.workspace import validate_workspace

ALLOWLISTED_RUNNERS = ("pytest",)
DEFAULT_TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 262_144
MAX_TIMEOUT_SECONDS = 300

TestStatus = Literal[
    "PASSED",
    "FAILED",
    "TIMED_OUT",
    "CANCELLED",
    "INCOMPLETE",
    "NOT_EXECUTED",
]


class TestingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TestSpecification(TestingModel):
    __test__ = False
    schema_version: str = "1"
    specification_id: str
    workspace_identifier: str
    runner: str
    arguments: list[str] = Field(default_factory=list)
    working_directory: str = "."
    timeout_seconds: int = Field(
        default=DEFAULT_TIMEOUT_SECONDS, ge=1, le=MAX_TIMEOUT_SECONDS
    )
    max_output_bytes: int = Field(default=MAX_OUTPUT_BYTES, ge=1024, le=1_048_576)
    digest: str = ""


class TestApproval(TestingModel):
    __test__ = False
    specification_id: str
    specification_digest: str
    workspace_identifier: str


class TestExecutionResult(TestingModel):
    __test__ = False
    execution_id: str
    specification_digest: str
    runner: str
    arguments: list[str]
    status: TestStatus
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    output_truncated: bool = False
    error: str | None = None


class TestEvidence(TestingModel):
    __test__ = False
    specification_digest: str
    approval_bound: bool
    runner_allowlisted: bool
    execution_completed: bool
    exit_code_zero: bool
    output_integrity: bool


class TestRunnerError(ValueError):
    __test__ = False
    pass


def _digest_payload(spec: TestSpecification) -> str:
    payload = spec.model_dump(exclude={"digest"}, mode="json")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def make_test_spec(
    workspace: Path,
    runner: str = "pytest",
    arguments: list[str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    working_directory: str = ".",
) -> TestSpecification:
    root = validate_workspace(workspace)
    if runner not in ALLOWLISTED_RUNNERS:
        raise TestRunnerError(
            f"Runner '{runner}' is not in allowlist: {ALLOWLISTED_RUNNERS}"
        )

    clean_args = list(arguments or [])
    # Validate arguments - disallow dangerous shell escapes, bash -c, arbitrary commands
    for arg in clean_args:
        if any(char in arg for char in [";", "&", "|", "`", "$", "\n", "\r"]):
            raise TestRunnerError(f"Argument contains unsafe shell characters: {arg}")

    draft = TestSpecification(
        specification_id=uuid4().hex,
        workspace_identifier=root.name,
        runner=runner,
        arguments=clean_args,
        working_directory=working_directory,
        timeout_seconds=timeout_seconds,
        digest="",
    )
    return draft.model_copy(update={"digest": _digest_payload(draft)})


def validate_test_spec(spec: TestSpecification, workspace: Path) -> TestSpecification:
    root = validate_workspace(workspace)
    if spec.workspace_identifier != root.name:
        msg = (
            f"Workspace mismatch: expected {root.name}, got {spec.workspace_identifier}"
        )
        raise TestRunnerError(msg)
    expected_digest = _digest_payload(spec)
    if spec.digest != expected_digest:
        raise TestRunnerError("Specification digest does not match content")
    if spec.runner not in ALLOWLISTED_RUNNERS:
        raise TestRunnerError(
            f"Runner '{spec.runner}' is not in allowlist: {ALLOWLISTED_RUNNERS}"
        )
    for arg in spec.arguments:
        if any(char in arg for char in [";", "&", "|", "`", "$", "\n", "\r"]):
            raise TestRunnerError(f"Argument contains unsafe shell characters: {arg}")
    return spec


def approve_test(spec: TestSpecification, workspace: Path) -> TestApproval:
    root = validate_workspace(workspace)
    validate_test_spec(spec, root)
    return TestApproval(
        specification_id=spec.specification_id,
        specification_digest=spec.digest,
        workspace_identifier=root.name,
    )


def execute_test(
    spec: TestSpecification,
    approval: TestApproval,
    workspace: Path,
) -> TestExecutionResult:
    root = validate_workspace(workspace)
    if (
        approval.specification_id != spec.specification_id
        or approval.specification_digest != spec.digest
        or approval.workspace_identifier != root.name
    ):
        raise TestRunnerError(
            "Approval is not bound to this exact specification and workspace"
        )

    validate_test_spec(spec, root)

    workdir = (root / spec.working_directory).resolve()
    if root not in (workdir, *workdir.parents):
        raise TestRunnerError("Working directory resolves outside workspace")

    # Command construction: only allowlisted python -m pytest
    cmd = [sys.executable, "-m", "pytest", *spec.arguments]

    execution_id = uuid4().hex
    start_time = time.monotonic()
    status: TestStatus = "NOT_EXECUTED"
    exit_code: int | None = None
    stdout_str = ""
    stderr_str = ""
    truncated = False
    err_msg: str | None = None

    try:
        # Launch with session/process group if supported to allow clean timeout kill
        kwargs: dict[str, object] = {
            "cwd": str(workdir),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if os.name != "nt":
            kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **kwargs)  # noqa: S603

        try:
            raw_out, raw_err = proc.communicate(timeout=spec.timeout_seconds)
            exit_code = proc.returncode
            duration = time.monotonic() - start_time

            if len(raw_out) > spec.max_output_bytes:
                raw_out = raw_out[: spec.max_output_bytes]
                truncated = True
            if len(raw_err) > spec.max_output_bytes:
                raw_err = raw_err[: spec.max_output_bytes]
                truncated = True

            stdout_str = raw_out.decode("utf-8", errors="replace")
            stderr_str = raw_err.decode("utf-8", errors="replace")

            if exit_code == 0:
                status = "PASSED"
            else:
                status = "FAILED"

        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start_time
            status = "TIMED_OUT"
            err_msg = f"Test execution timed out after {spec.timeout_seconds} seconds"
            # Terminate entire process group safely
            if os.name != "nt":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    pass
            else:
                proc.kill()
            try:
                proc.communicate(timeout=2)
            except Exception:
                pass

    except Exception as exc:
        duration = time.monotonic() - start_time
        status = "FAILED"
        err_msg = f"Process invocation error: {exc}"

    return TestExecutionResult(
        execution_id=execution_id,
        specification_digest=spec.digest,
        runner=spec.runner,
        arguments=spec.arguments,
        status=status,
        exit_code=exit_code,
        duration_seconds=round(duration, 3),
        stdout=stdout_str,
        stderr=stderr_str,
        output_truncated=truncated,
        error=err_msg,
    )


def load_test_spec(path: Path) -> TestSpecification:
    """Load untrusted test specification safely from JSON file."""
    if path.is_symlink() or path.stat().st_size > 1_000_000:
        raise TestRunnerError("Test specification file is unsafe or exceeds size limit")
    try:
        return TestSpecification.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise TestRunnerError("Test specification file is invalid") from error
