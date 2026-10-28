"""CLI regression tests for coordinator-owned external agent commands."""

from __future__ import annotations

import asyncio
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
from zeroagent.execution.service import ApprovalStore, make_request, request_digest

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

    async def cancel(self, execution_id: str | None = None) -> None:
        del execution_id
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


def test_agent_validate_returns_fingerprint_not_authorization(tmp_path: Path) -> None:
    from zeroagent.cli import app

    preview = runner.invoke(
        app, ["agent", "validate", "safe task", "--workspace", str(tmp_path)]
    )
    payload = json.loads(preview.output)
    assert "request_fingerprint" in payload
    assert "approval_token" not in payload


def test_single_use_approval_rejects_changed_request_and_replay(tmp_path: Path) -> None:
    config = Settings(agent_execution_enabled=True, opencode_enabled=True)
    store = ApprovalStore(tmp_path / "approvals")
    engine = ExecutionCoordinator(
        AdapterRegistry([SuccessfulAdapter()]),
        settings=config,
        approval_authorizer=lambda request: store.consume(
            request.approval_token,
            request_digest(
                adapter_id=request.adapter_id,
                workspace=request.workspace,
                prompt=request.prompt,
                timeout_seconds=request.timeout_seconds,
                record_evidence=request.record_evidence,
                settings=config,
            ),
        ),
    )
    fingerprint = request_digest(
        adapter_id="opencode",
        workspace=tmp_path,
        prompt="safe task",
        timeout_seconds=None,
        record_evidence=False,
        settings=config,
    )
    token = store.issue(fingerprint)
    changed = make_request(
        adapter_id="opencode",
        workspace=tmp_path,
        prompt="changed task",
        timeout_seconds=None,
        record_evidence=False,
        approval_token=token,
    )
    assert asyncio.run(engine.execute(changed)).state.value == "FAILED"
    approved = make_request(
        adapter_id="opencode",
        workspace=tmp_path,
        prompt="safe task",
        timeout_seconds=None,
        record_evidence=False,
        approval_token=token,
    )
    assert asyncio.run(engine.execute(approved)).state.value == "FAILED"


def test_single_use_approval_allows_only_one_concurrent_request(tmp_path: Path) -> None:
    config = Settings(agent_execution_enabled=True, opencode_enabled=True)
    store = ApprovalStore(tmp_path / "approvals")
    fingerprint = request_digest(
        adapter_id="opencode",
        workspace=tmp_path,
        prompt="safe task",
        timeout_seconds=None,
        record_evidence=False,
        settings=config,
    )
    token = store.issue(fingerprint)
    engine = ExecutionCoordinator(
        AdapterRegistry([SuccessfulAdapter()]),
        settings=config,
        approval_authorizer=lambda request: store.consume(
            request.approval_token, fingerprint
        ),
    )

    async def run() -> list[str]:
        requests = [
            make_request(
                adapter_id="opencode",
                workspace=tmp_path,
                prompt="safe task",
                timeout_seconds=None,
                record_evidence=False,
                approval_token=token,
            )
            for _ in range(2)
        ]
        return [
            result.state.value
            for result in await asyncio.gather(
                *(engine.execute(value) for value in requests)
            )
        ]

    assert sorted(asyncio.run(run())) == ["FAILED", "SUCCEEDED"]


def test_agent_cancel_does_not_claim_cross_process_support() -> None:
    from zeroagent.cli import app

    result = runner.invoke(app, ["agent", "cancel", "unknown"])
    assert result.exit_code == 2
    assert "cross-process cancellation is unsupported" in result.output
