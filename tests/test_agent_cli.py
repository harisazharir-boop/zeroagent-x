"""CLI regression tests for coordinator-owned external agent commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from zeroagent.config import Settings
from zeroagent.execution.adapters import AgentAdapter
from zeroagent.execution.coordinator import ExecutionCoordinator
from zeroagent.execution.models import (
    AdapterCapabilities,
    AdapterResult,
    ExecutionRequest,
)
from zeroagent.execution.registry import AdapterRegistry

runner = CliRunner()


class SuccessfulAdapter(AgentAdapter):
    identifier = "opencode"

    def available(self) -> bool:
        return True

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(capabilities=frozenset({"read_only_prompt"}))

    def validate(self, request: ExecutionRequest) -> None:
        del request

    async def execute(self, request: ExecutionRequest) -> AdapterResult:
        del request
        return AdapterResult(exit_code=0, stdout='{"type":"text","text":"ok"}')

    async def cancel(self) -> None:
        return None


def coordinator() -> ExecutionCoordinator:
    return ExecutionCoordinator(
        AdapterRegistry([SuccessfulAdapter()]),
        settings=Settings(agent_execution_enabled=True, opencode_enabled=True),
    )


def test_agent_commands_discoverable_and_default_policy_denies(tmp_path: Path) -> None:
    from zeroagent.cli import app

    help_result = runner.invoke(app, ["agent", "--help"])
    denied = runner.invoke(app, ["agent", "run", "hello", "--workspace", str(tmp_path)])
    assert help_result.exit_code == 0
    assert "adapters" in help_result.output
    assert "validate" in help_result.output
    assert denied.exit_code == 2
    assert "disabled by policy" in denied.output


def test_agent_run_requires_request_bound_approval(tmp_path: Path, monkeypatch) -> None:
    from zeroagent.cli import app

    monkeypatch.setattr("zeroagent.cli.make_coordinator", lambda **_: coordinator())
    preview = runner.invoke(
        app, ["agent", "validate", "safe task", "--workspace", str(tmp_path)]
    )
    digest = json.loads(preview.output)["approval_digest"]
    stale = runner.invoke(
        app,
        [
            "agent",
            "run",
            "changed task",
            "--workspace",
            str(tmp_path),
            "--approve-digest",
            digest,
        ],
    )
    approved = runner.invoke(
        app,
        [
            "agent",
            "run",
            "safe task",
            "--workspace",
            str(tmp_path),
            "--approve-digest",
            digest,
        ],
    )
    assert stale.exit_code == 2
    assert "Explicit approval is required" in stale.output
    assert approved.exit_code == 0
    assert json.loads(approved.output)["state"] == "SUCCEEDED"


def test_agent_cancel_does_not_claim_cross_process_support() -> None:
    from zeroagent.cli import app

    result = runner.invoke(app, ["agent", "cancel", "unknown"])
    assert result.exit_code == 2
    assert "cross-process cancellation is unsupported" in result.output
