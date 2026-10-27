"""Single-run pipeline lifecycle and approval-bound integration tests."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path

import pytest

import zeroagent.editing as editing
from zeroagent.editing import FileChange, make_proposal
from zeroagent.pipeline import PipelineEngine, PipelineError, PipelineState
from zeroagent.testing import make_test_spec


def _proposal(workspace: Path):
    content = "updated\n"
    return make_proposal(
        workspace,
        [
            FileChange(
                path="app.txt",
                operation="modify",
                original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                new_content=content,
                resulting_sha256=hashlib.sha256(content.encode()).hexdigest(),
            )
        ],
        "Controlled change",
    )


def test_pipeline_is_off_until_explicit_start(tmp_path: Path) -> None:
    engine = PipelineEngine()
    assert engine.state is PipelineState.OFF
    assert engine.active_run is None
    assert engine.last_run is None


def test_pipeline_starts_read_only_then_waits_for_user_proposal(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    events: list[tuple[str, str, str]] = []
    engine = PipelineEngine(
        lambda title, detail, kind: events.append((title, detail, kind))
    )
    run = engine.start("Improve app", tmp_path)
    assert run.state is PipelineState.AWAITING_APPROVAL
    assert run.awaiting == "EDIT_PROPOSAL"
    assert [stage.name for stage in run.stages] == ["PLAN", "ANALYZE"]
    assert (tmp_path / "app.txt").read_text() == "old\n"
    assert events[0][0] == "pipeline started"
    with pytest.raises(PipelineError, match="already active"):
        engine.start("Second run", tmp_path)


def test_pipeline_approval_is_exact_and_cancel_clears_all_run_resources(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    engine = PipelineEngine()
    engine.start("Improve app", tmp_path)
    proposal = _proposal(tmp_path)
    assert "-old" in engine.submit_proposal(proposal, tmp_path)
    assert engine.state is PipelineState.AWAITING_APPROVAL
    with pytest.raises(PipelineError, match="does not match"):
        engine.approve_edit("wrong", tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    assert engine.patch_approval is not None
    assert engine.active_run and engine.active_run.awaiting == "APPLY_EDIT"
    result = engine.cancel()
    assert result and result.state is PipelineState.CANCELLED
    assert engine.state is PipelineState.OFF
    assert engine.active_run is None
    assert engine.proposal is None
    assert engine.patch_approval is None
    assert result.stages[-1].name == "CANCELLED"
    assert engine.cancel() is result


def test_pipeline_test_approval_cannot_cross_runs(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    engine = PipelineEngine()
    engine.start("Improve app", tmp_path)
    engine.cancel()


@pytest.mark.asyncio
async def test_async_pipeline_waiter_cancels_without_orphan_task(
    tmp_path: Path,
) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def stage() -> None:
        entered.set()
        await release.wait()

    engine = PipelineEngine()
    await engine.start_async("Wait safely", tmp_path, stage)
    await entered.wait()
    assert engine.active_task_count == 1
    assert engine.state is PipelineState.PREPARING
    result = await engine.cancel_async()
    assert result and result.state is PipelineState.CANCELLED
    assert engine.state is PipelineState.OFF
    assert engine.active_task_count == 0
    assert engine.pending_approval_count == 0
    release.set()


@pytest.mark.asyncio
async def test_async_pipeline_cancellation_invalidates_approval_waiter(
    tmp_path: Path,
) -> None:
    engine = PipelineEngine()
    await engine.start_async("Wait for approval", tmp_path)
    for _ in range(10):
        if engine.pending_approval_count:
            break
        await asyncio.sleep(0)
    assert engine.state is PipelineState.AWAITING_APPROVAL
    assert engine.pending_approval_count == 1
    old_run = engine.active_run
    await engine.cancel_async()
    assert engine.last_run and engine.last_run.state is PipelineState.CANCELLED
    assert engine.pending_approval_count == 0
    await engine.start_async("New run", tmp_path)
    assert engine.active_run and engine.active_run.run_id != old_run.run_id
    await engine.cancel_async()


@pytest.mark.asyncio
async def test_shutdown_is_idempotent_and_permanently_rejects_start(
    tmp_path: Path,
) -> None:
    events: list[tuple[str, str, str]] = []
    engine = PipelineEngine(lambda *event: events.append(event))
    await engine.start_async("Shutdown", tmp_path)
    result = await engine.shutdown_async()
    assert result and result.state is PipelineState.CANCELLED
    assert await engine.shutdown_async() is result
    with pytest.raises(PipelineError, match="shut down"):
        engine.start("No restart", tmp_path)
    assert [event[0] for event in events].count("pipeline cancelled") == 1


def test_event_sink_failure_does_not_break_lifecycle(tmp_path: Path) -> None:
    engine = PipelineEngine(lambda *_: (_ for _ in ()).throw(RuntimeError("sink")))
    engine.start("Still safe", tmp_path)
    result = engine.cancel()
    assert result and result.state is PipelineState.CANCELLED
    engine.start("Improve app", tmp_path)
    spec = make_test_spec(tmp_path, arguments=["-q"])
    with pytest.raises(PipelineError, match="different action"):
        engine.submit_test_spec(spec, tmp_path)
    engine.cancel()


def test_pipeline_applies_once_then_executes_approved_passing_test(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    (tmp_path / "test_app.py").write_text(
        "def test_updated():\n    assert open('app.txt').read() == 'updated\\n'\n"
    )
    engine = PipelineEngine()
    engine.start("Improve app", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    recovery = tmp_path.parent / f"{tmp_path.name}-recovery"
    result = engine.execute_approved_edit(tmp_path, recovery)
    assert result.applied_paths == ["app.txt"]
    assert (tmp_path / "app.txt").read_text() == "updated\n"
    with pytest.raises(PipelineError, match="different action"):
        engine.execute_approved_edit(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-other"
        )
    spec = make_test_spec(tmp_path, arguments=["-q"])
    engine.submit_test_spec(spec, tmp_path)
    engine.approve_test(spec.digest, tmp_path)
    test_result = engine.execute_approved_test(tmp_path)
    assert test_result.status == "PASSED"
    assert engine.state is PipelineState.OFF
    assert engine.last_run and engine.last_run.state is PipelineState.COMPLETED
    assert engine.last_report and engine.last_report.test_status == "PASSED"
    assert engine.last_report.proof_status == "INCOMPLETE"


def test_pipeline_rejects_cross_workspace_and_unapproved_apply(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    other = tmp_path.parent / "other-workspace"
    other.mkdir()
    (other / "app.txt").write_bytes(b"old\n")
    engine = PipelineEngine()
    engine.start("Improve app", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    with pytest.raises(PipelineError, match="different action"):
        engine.execute_approved_edit(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    with pytest.raises(PipelineError, match="bound"):
        engine.approve_edit(proposal.digest, other)
    engine.approve_edit(proposal.digest, tmp_path)
    with pytest.raises(PipelineError, match="bound"):
        engine.execute_approved_edit(
            other, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    engine.cancel()


def test_pipeline_explicit_skips_remain_incomplete(tmp_path: Path) -> None:
    engine = PipelineEngine()
    engine.start("Inspect only", tmp_path)
    engine.skip_edit("No source change requested")
    assert engine.active_run and engine.active_run.awaiting == "TEST_SPECIFICATION"
    engine.skip_test("No test command requested")
    assert engine.state is PipelineState.OFF
    assert engine.last_report and engine.last_report.skipped_stages == ["EDIT", "TEST"]
    assert engine.last_report.apply_status == "NOT_EXECUTED"
    assert engine.last_report.test_status == "NOT_EXECUTED"


def test_pipeline_failing_and_timed_out_tests_are_not_success(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    (tmp_path / "test_app.py").write_text("def test_failure():\n    assert False\n")
    engine = PipelineEngine()
    engine.start("Improve app", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    engine.execute_approved_edit(
        tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
    )
    spec = make_test_spec(tmp_path, arguments=["-q"])
    engine.submit_test_spec(spec, tmp_path)
    engine.approve_test(spec.digest, tmp_path)
    failed = engine.execute_approved_test(tmp_path)
    assert failed.status == "FAILED"
    assert engine.last_run and engine.last_run.state is PipelineState.FAILED
    assert engine.last_report and engine.last_report.test_status == "FAILED"

    timeout_workspace = tmp_path.parent / f"{tmp_path.name}-timeout"
    timeout_workspace.mkdir()
    (timeout_workspace / "app.txt").write_bytes(b"old\n")
    (timeout_workspace / "test_slow.py").write_text(
        "import time\ndef test_slow():\n    time.sleep(2)\n"
    )
    engine = PipelineEngine()
    engine.start("Timeout", timeout_workspace)
    proposal = _proposal(timeout_workspace)
    engine.submit_proposal(proposal, timeout_workspace)
    engine.approve_edit(proposal.digest, timeout_workspace)
    engine.execute_approved_edit(
        timeout_workspace,
        timeout_workspace.parent / f"{timeout_workspace.name}-recovery",
    )
    spec = make_test_spec(timeout_workspace, arguments=["-q"], timeout_seconds=1)
    engine.submit_test_spec(spec, timeout_workspace)
    engine.approve_test(spec.digest, timeout_workspace)
    timed_out = engine.execute_approved_test(timeout_workspace)
    assert timed_out.status == "TIMED_OUT"
    assert engine.last_run and engine.last_run.state is PipelineState.FAILED
    assert engine.last_report and engine.last_report.test_status == "TIMED_OUT"


def test_changed_artifacts_and_old_approvals_cannot_execute(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    engine = PipelineEngine()
    engine.start("Edit", tmp_path)
    original = _proposal(tmp_path)
    engine.submit_proposal(original, tmp_path)
    engine.approve_edit(original.digest, tmp_path)
    changed = original.model_copy(update={"explanation": "changed after approval"})
    engine.proposal = changed
    with pytest.raises(Exception):  # noqa: B017
        engine.execute_approved_edit(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    assert (tmp_path / "app.txt").read_text() == "old\n"
    assert engine.last_run and engine.last_run.state is PipelineState.FAILED

    engine = PipelineEngine()
    engine.start("First", tmp_path)
    first = _proposal(tmp_path)
    engine.submit_proposal(first, tmp_path)
    engine.approve_edit(first.digest, tmp_path)
    old_approval = engine.patch_approval
    engine.cancel()
    engine.start("Second", tmp_path)
    second = _proposal(tmp_path)
    engine.submit_proposal(second, tmp_path)
    engine.approve_edit(second.digest, tmp_path)
    engine.patch_approval = old_approval
    with pytest.raises(Exception):  # noqa: B017
        engine.execute_approved_edit(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-second"
        )
    assert (tmp_path / "app.txt").read_text() == "old\n"


def test_changed_test_spec_and_duplicate_test_execution_reject(tmp_path: Path) -> None:
    engine = _approved_test_engine(tmp_path)
    assert engine.test_spec
    changed = engine.test_spec.model_copy(update={"arguments": ["-q", "-x"]})
    engine.test_spec = changed
    with pytest.raises(Exception):  # noqa: B017
        engine.execute_approved_test(tmp_path)
    assert engine.last_run and engine.last_run.state is PipelineState.FAILED

    duplicate_workspace = tmp_path.parent / f"{tmp_path.name}-duplicate"
    duplicate_workspace.mkdir()
    (duplicate_workspace / "test_pass.py").write_text(
        "def test_pass():\n    assert True\n"
    )
    engine = _approved_test_engine(duplicate_workspace)
    result = engine.execute_approved_test(duplicate_workspace)
    assert result.status == "PASSED"
    with pytest.raises(PipelineError):
        engine.execute_approved_test(duplicate_workspace)


def test_apply_failure_records_failed_terminal_report(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    engine = PipelineEngine()
    engine.start("Fail apply", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    (tmp_path / "app.txt").write_text("changed externally\n")
    with pytest.raises(Exception):  # noqa: B017
        engine.execute_approved_edit(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    assert engine.last_run and engine.last_run.state is PipelineState.FAILED
    assert engine.last_report and engine.last_report.apply_status == "NOT_EXECUTED"
    assert any(stage.outcome == "FAILED" for stage in engine.last_run.stages)


@pytest.mark.asyncio
async def test_cancel_async_waits_for_owned_apply_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "app.txt").write_bytes(b"old\n")
    entered = threading.Event()
    release = threading.Event()
    original_apply = pipeline_module.apply

    def blocked_apply(*args, **kwargs):
        entered.set()
        release.wait()
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "apply", blocked_apply)
    engine = PipelineEngine()
    engine.start("Improve app", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    operation = asyncio.create_task(
        engine.execute_approved_edit_async(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    )
    await asyncio.to_thread(entered.wait)
    cancellation = asyncio.create_task(engine.cancel_async())
    await asyncio.sleep(0)
    assert engine.state is PipelineState.CANCELLING
    assert engine.active_operation == "APPLY_EDIT"
    assert engine.active_task_count == 1
    release.set()
    await operation
    result = await cancellation
    assert result and result.state is PipelineState.CANCELLED
    assert engine.state is PipelineState.OFF
    assert engine.active_task_count == 0


def _approved_test_engine(
    tmp_path: Path, recovery_suffix: str = "recovery"
) -> PipelineEngine:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    engine = PipelineEngine()
    engine.start("Run test", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    engine.execute_approved_edit(
        tmp_path, tmp_path.parent / f"{tmp_path.name}-{recovery_suffix}"
    )
    spec = make_test_spec(tmp_path, arguments=["-q"])
    engine.submit_test_spec(spec, tmp_path)
    engine.approve_test(spec.digest, tmp_path)
    return engine


@pytest.mark.asyncio
async def test_cancel_async_waits_for_owned_test_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    entered = threading.Event()
    release = threading.Event()
    original = pipeline_module.execute_test

    def blocked(*args, **kwargs):
        entered.set()
        release.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "execute_test", blocked)
    engine = _approved_test_engine(tmp_path)
    operation = asyncio.create_task(engine.execute_approved_test_async(tmp_path))
    try:
        await asyncio.to_thread(entered.wait)
        cancellation = asyncio.create_task(engine.cancel_async())
        await asyncio.sleep(0)
        assert engine.state is PipelineState.CANCELLING
        assert engine.active_operation == "RUN_TEST"
        assert engine.active_task_count == 1
    finally:
        release.set()
    await operation
    result = await cancellation
    assert result and result.state is PipelineState.CANCELLED
    assert engine.state is PipelineState.OFF
    assert engine.active_operation is None
    assert engine.active_task_count == 0


@pytest.mark.asyncio
async def test_shutdown_waits_for_owned_apply_and_rejects_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "app.txt").write_bytes(b"old\n")
    entered = threading.Event()
    release = threading.Event()
    original = pipeline_module.apply

    def blocked(*args, **kwargs):
        entered.set()
        release.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "apply", blocked)
    engine = PipelineEngine()
    engine.start("Apply", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    operation = asyncio.create_task(
        engine.execute_approved_edit_async(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    )
    try:
        await asyncio.to_thread(entered.wait)
        shutdown = asyncio.create_task(engine.shutdown_async())
        await asyncio.sleep(0)
        assert engine.state is PipelineState.CANCELLING
        assert engine.active_operation == "APPLY_EDIT"
    finally:
        release.set()
    await operation
    result = await shutdown
    assert result and result.state is PipelineState.CANCELLED
    with pytest.raises(PipelineError, match="shut down"):
        engine.start("No restart", tmp_path)


@pytest.mark.asyncio
async def test_shutdown_waits_for_owned_test_and_terminal_event_follows_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    entered = threading.Event()
    release = threading.Event()
    events: list[str] = []
    original = pipeline_module.execute_test

    def blocked(*args, **kwargs):
        entered.set()
        release.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "execute_test", blocked)
    engine = _approved_test_engine(tmp_path)
    engine._event_sink = lambda title, *_: events.append(title)
    operation = asyncio.create_task(engine.execute_approved_test_async(tmp_path))
    try:
        await asyncio.to_thread(entered.wait)
        shutdown = asyncio.create_task(engine.shutdown_async())
        await asyncio.sleep(0)
        assert engine.state is PipelineState.CANCELLING
        assert engine.active_operation == "RUN_TEST"
        assert engine.active_task_count == 1
        assert "pipeline cancelled" not in events
    finally:
        release.set()
    await operation
    result = await shutdown
    assert result and result.state is PipelineState.CANCELLED
    assert engine.last_report is not None
    assert events.count("pipeline cancelled") == 1
    assert events.index("pipeline waiting for active operation") < events.index(
        "pipeline cancelled"
    )
    assert await engine.shutdown_async() is result
    with pytest.raises(PipelineError, match="shut down"):
        engine.start("No restart", tmp_path)


@pytest.mark.asyncio
async def test_concurrent_stops_finalize_once_after_owned_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "app.txt").write_bytes(b"old\n")
    entered, release = threading.Event(), threading.Event()
    events: list[str] = []
    original = pipeline_module.apply

    def blocked(*args, **kwargs):
        entered.set()
        release.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "apply", blocked)
    engine = PipelineEngine(lambda title, *_: events.append(title))
    engine.start("Apply", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    operation = asyncio.create_task(
        engine.execute_approved_edit_async(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    )
    try:
        await asyncio.to_thread(entered.wait)
        stops = asyncio.gather(engine.cancel_async("one"), engine.cancel_async("two"))
        await asyncio.sleep(0)
        assert engine.state is PipelineState.CANCELLING
        with pytest.raises(PipelineError, match="already active"):
            engine.start("Blocked", tmp_path)
    finally:
        release.set()
    await operation
    first, second = await stops
    assert first is second and first and first.state is PipelineState.CANCELLED
    assert events.count("pipeline cancelled") == 1
    assert engine.active_task_count == 0


@pytest.mark.asyncio
async def test_concurrent_async_execution_claims_allow_one_apply_and_one_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "app.txt").write_bytes(b"old\n")
    entered, release = threading.Event(), threading.Event()
    calls = 0
    original_apply = pipeline_module.apply

    def blocked_apply(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait()
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "apply", blocked_apply)
    engine = PipelineEngine()
    engine.start("Apply", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    first = asyncio.create_task(
        engine.execute_approved_edit_async(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    )
    await asyncio.to_thread(entered.wait)
    with pytest.raises(PipelineError):
        await engine.execute_approved_edit_async(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-other"
        )
    release.set()
    await first
    assert calls == 1


def test_cross_run_identical_test_approval_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert True\n")
    first = _approved_test_engine(tmp_path)
    old_approval = first.test_approval
    old_spec = first.test_spec
    first.cancel()
    second = _approved_test_engine(tmp_path, "second-recovery")
    assert old_approval and old_spec and second.test_spec
    # Same valid spec bytes/digest, but old approval owner belongs to first run.
    second.test_spec = old_spec
    second.test_approval = old_approval
    with pytest.raises(PipelineError, match="replaced after authorization"):
        second.execute_approved_test(tmp_path)
    assert second.active_run and second.active_run.awaiting == "RUN_TEST"


@pytest.mark.asyncio
async def test_concurrent_test_claims_allow_single_guarded_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    entered, release = threading.Event(), threading.Event()
    calls = 0
    original = pipeline_module.execute_test

    def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "execute_test", blocked)
    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert True\n")
    engine = _approved_test_engine(tmp_path)
    first = asyncio.create_task(engine.execute_approved_test_async(tmp_path))
    try:
        await asyncio.to_thread(entered.wait)
        with pytest.raises(PipelineError):
            await engine.execute_approved_test_async(tmp_path)
    finally:
        release.set()
    result = await first
    assert result.status == "PASSED"
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_stop_and_shutdown_finalize_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "app.txt").write_bytes(b"old\n")
    entered, release = threading.Event(), threading.Event()
    events: list[str] = []
    original = pipeline_module.apply

    def blocked(*args, **kwargs):
        entered.set()
        release.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "apply", blocked)
    engine = PipelineEngine(lambda title, *_: events.append(title))
    engine.start("Apply", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    operation = asyncio.create_task(
        engine.execute_approved_edit_async(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    )
    try:
        await asyncio.to_thread(entered.wait)
        stop, shutdown = engine.cancel_async(), engine.shutdown_async()
        combined = asyncio.gather(stop, shutdown)
        await asyncio.sleep(0)
        assert engine.state is PipelineState.CANCELLING
    finally:
        release.set()
    await operation
    results = await combined
    assert all(result and result.state is PipelineState.CANCELLED for result in results)
    assert events.count("pipeline cancelled") == 1
    with pytest.raises(PipelineError, match="shut down"):
        engine.start("No restart", tmp_path)


def test_safe_edit_partial_failure_retains_backup_without_false_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from zeroagent.editing import FileChange, apply, approve, make_proposal

    (tmp_path / "a.txt").write_bytes(b"old-a\n")
    (tmp_path / "b.txt").write_bytes(b"old-b\n")
    changes = [
        FileChange(
            path="a.txt",
            operation="modify",
            original_sha256=hashlib.sha256(b"old-a\n").hexdigest(),
            new_content="new-a\n",
            resulting_sha256=hashlib.sha256(b"new-a\n").hexdigest(),
        ),
        FileChange(
            path="b.txt",
            operation="modify",
            original_sha256=hashlib.sha256(b"old-b\n").hexdigest(),
            new_content="new-b\n",
            resulting_sha256=hashlib.sha256(b"new-b\n").hexdigest(),
        ),
    ]
    proposal = make_proposal(tmp_path, changes, "two files")
    approval = approve(proposal, tmp_path)
    original_replace = editing.os.replace

    def fail_second(source, target):
        if Path(target).name == "b.txt":
            raise OSError("controlled second replacement failure")
        return original_replace(source, target)

    monkeypatch.setattr(editing.os, "replace", fail_second)
    recovery = tmp_path.parent / f"{tmp_path.name}-recovery"
    with pytest.raises(Exception, match="partially applied"):
        apply(proposal, approval, tmp_path, recovery)
    assert (tmp_path / "a.txt").read_text() == "new-a\n"
    assert (tmp_path / "b.txt").read_text() == "old-b\n"
    assert (recovery / "0.bak").read_text() == "old-a\n"
    assert not (recovery / "manifest.json").exists()


@pytest.mark.asyncio
async def test_apply_failure_after_stop_preserves_failed_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "app.txt").write_bytes(b"old\n")
    entered, release = threading.Event(), threading.Event()

    def failing_apply(*_args, **_kwargs):
        entered.set()
        release.wait()
        raise RuntimeError("controlled apply failure")

    monkeypatch.setattr(pipeline_module, "apply", failing_apply)
    engine = PipelineEngine()
    engine.start("Apply", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    operation = asyncio.create_task(
        engine.execute_approved_edit_async(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    )
    try:
        await asyncio.to_thread(entered.wait)
        cancellation = asyncio.create_task(engine.cancel_async())
        await asyncio.sleep(0)
        assert engine.state is PipelineState.CANCELLING
    finally:
        release.set()
    with pytest.raises(RuntimeError, match="controlled apply failure"):
        await operation
    result = await cancellation
    assert result and result.state is PipelineState.CANCELLED
    assert any(
        stage.name == "APPLY_EDIT" and stage.outcome == "FAILED"
        for stage in result.stages
    )
    assert engine.last_report and engine.last_report.apply_status == "NOT_EXECUTED"
    assert engine.active_task_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["FAILED", "TIMED_OUT"])
async def test_test_result_after_stop_preserves_actual_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    import zeroagent.pipeline.engine as pipeline_module
    from zeroagent.testing import TestExecutionResult

    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert True\n")
    entered, release = threading.Event(), threading.Event()

    def blocked_result(*_args, **_kwargs):
        entered.set()
        release.wait()
        return TestExecutionResult(
            execution_id="controlled",
            specification_digest="a" * 64,
            runner="pytest",
            arguments=["-q"],
            status=status,
            exit_code=1 if status == "FAILED" else None,
            duration_seconds=0.0,
            stdout="",
            stderr="",
            error="controlled result",
        )

    monkeypatch.setattr(pipeline_module, "execute_test", blocked_result)
    engine = _approved_test_engine(tmp_path)
    operation = asyncio.create_task(engine.execute_approved_test_async(tmp_path))
    try:
        await asyncio.to_thread(entered.wait)
        cancellation = asyncio.create_task(engine.cancel_async())
        await asyncio.sleep(0)
        assert engine.state is PipelineState.CANCELLING
    finally:
        release.set()
    outcome = await operation
    result = await cancellation
    assert outcome.status == status
    assert result and result.state is PipelineState.CANCELLED
    assert engine.last_report and engine.last_report.test_status == status
    assert all(stage.name != "VERIFY" for stage in result.stages)
    assert engine.active_task_count == 0


@pytest.mark.asyncio
async def test_mixed_async_apply_owner_rejects_sync_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "app.txt").write_bytes(b"old\n")
    entered, release = threading.Event(), threading.Event()
    calls = 0
    original = pipeline_module.apply

    def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "apply", blocked)
    engine = PipelineEngine()
    engine.start("Apply", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    owner = asyncio.create_task(
        engine.execute_approved_edit_async(
            tmp_path, tmp_path.parent / f"{tmp_path.name}-recovery"
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert engine.active_operation == "APPLY_EDIT"
        with pytest.raises(PipelineError):
            await asyncio.wait_for(
                asyncio.to_thread(
                    engine.execute_approved_edit,
                    tmp_path,
                    tmp_path.parent / f"{tmp_path.name}-other",
                ),
                5,
            )
        assert engine.active_operation == "APPLY_EDIT"
        assert calls == 1
    finally:
        release.set()
    await asyncio.wait_for(owner, 5)
    assert engine.active_operation is None
    assert [stage.name for stage in engine.active_run.stages].count("APPLY_EDIT") == 2


@pytest.mark.asyncio
async def test_mixed_sync_apply_owner_rejects_async_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "app.txt").write_bytes(b"old\n")
    entered, release = threading.Event(), threading.Event()
    calls = 0
    original = pipeline_module.apply

    def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "apply", blocked)
    engine = PipelineEngine()
    engine.start("Apply", tmp_path)
    proposal = _proposal(tmp_path)
    engine.submit_proposal(proposal, tmp_path)
    engine.approve_edit(proposal.digest, tmp_path)
    owner = asyncio.create_task(
        asyncio.to_thread(
            engine.execute_approved_edit,
            tmp_path,
            tmp_path.parent / f"{tmp_path.name}-recovery",
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert engine.active_operation == "APPLY_EDIT"
        with pytest.raises(PipelineError):
            await engine.execute_approved_edit_async(
                tmp_path, tmp_path.parent / f"{tmp_path.name}-other"
            )
        assert engine.active_operation == "APPLY_EDIT"
        assert calls == 1
    finally:
        release.set()
    await asyncio.wait_for(owner, 5)
    assert engine.active_operation is None


@pytest.mark.asyncio
async def test_mixed_async_test_owner_rejects_sync_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert True\n")
    entered, release = threading.Event(), threading.Event()
    calls = 0
    original = pipeline_module.execute_test

    def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "execute_test", blocked)
    engine = _approved_test_engine(tmp_path)
    owner = asyncio.create_task(engine.execute_approved_test_async(tmp_path))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert engine.active_operation == "RUN_TEST"
        with pytest.raises(PipelineError):
            await asyncio.wait_for(
                asyncio.to_thread(engine.execute_approved_test, tmp_path), 5
            )
        assert engine.active_operation == "RUN_TEST"
        assert calls == 1
    finally:
        release.set()
    result = await asyncio.wait_for(owner, 5)
    assert result.status == "PASSED"
    assert engine.active_operation is None


@pytest.mark.asyncio
async def test_mixed_sync_test_owner_rejects_async_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import zeroagent.pipeline.engine as pipeline_module

    (tmp_path / "test_pass.py").write_text("def test_pass():\n    assert True\n")
    entered, release = threading.Event(), threading.Event()
    calls = 0
    original = pipeline_module.execute_test

    def blocked(*args, **kwargs):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "execute_test", blocked)
    engine = _approved_test_engine(tmp_path)
    owner = asyncio.create_task(
        asyncio.to_thread(engine.execute_approved_test, tmp_path)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        assert engine.active_operation == "RUN_TEST"
        with pytest.raises(PipelineError):
            await engine.execute_approved_test_async(tmp_path)
        assert engine.active_operation == "RUN_TEST"
        assert calls == 1
    finally:
        release.set()
    result = await asyncio.wait_for(owner, 5)
    assert result.status == "PASSED"
    assert engine.active_operation is None
