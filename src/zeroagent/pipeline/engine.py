"""Single-run lifecycle without worker, polling, subprocess, or execution bridge."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

from zeroagent.core.repository import analyze_repository
from zeroagent.editing import (
    ApplicationResult,
    PatchApproval,
    PatchEvidence,
    PatchProposal,
    apply,
    approve,
    preview,
)
from zeroagent.pipeline.models import (
    PipelineReport,
    PipelineRun,
    PipelineState,
    StageEvidence,
    new_run,
)
from zeroagent.planning import TaskPlan, create_plan, validate_plan
from zeroagent.proof.engine import verify_execution
from zeroagent.proof.models import ProofReport
from zeroagent.security.workspace import validate_workspace
from zeroagent.testing import (
    TestApproval,
    TestEvidence,
    TestExecutionResult,
    TestSpecification,
    execute_test,
    validate_test_spec,
)
from zeroagent.testing import (
    approve_test as approve_test_spec,
)


class PipelineError(ValueError):
    """Explicit pipeline lifecycle contract violation."""


EventSink = Callable[[str, str, str], None]
StageRunner = Callable[[], Awaitable[None] | None]


class PipelineEngine:
    """One user-started run. Async API owns only its tracked task and waiter.

    ``start`` keeps compatibility and performs read-only Plan/Analyze synchronously.
    ``start_async`` uses same state records, then pauses on an event-driven approval
    waiter. Controlled operations remain synchronous and run only by explicit calls.
    """

    def __init__(self, event_sink: EventSink | None = None) -> None:
        self._event_sink = event_sink
        self.active_run: PipelineRun | None = None
        self.last_run: PipelineRun | None = None
        self.last_report: PipelineReport | None = None
        self.plan: TaskPlan | None = None
        self.analysis = None
        self.proposal: PatchProposal | None = None
        self.patch_approval: PatchApproval | None = None
        self._patch_approval_run_id: str | None = None
        self._patch_approval_identity: int | None = None
        self.test_spec: TestSpecification | None = None
        self.test_approval: TestApproval | None = None
        self._test_approval_run_id: str | None = None
        self._test_approval_identity: int | None = None
        self.application_result: ApplicationResult | None = None
        self.test_result: TestExecutionResult | None = None
        self.patch_proof: ProofReport | None = None
        self.test_proof: ProofReport | None = None
        self._workspace: Path | None = None
        self._applied = False
        self._tested = False
        self._patch_approval_run_id = None
        self._test_approval_run_id = None
        self._patch_approval_identity = None
        self._test_approval_identity = None
        self._task: asyncio.Task[None] | None = None
        self._operation_task: asyncio.Task[object] | None = None
        self._cancellation_lock: asyncio.Lock | None = None
        self._approval_waiter: asyncio.Event | None = None
        self._shutdown = False
        self.active_operation: str | None = None
        self._skipped_stages: list[str] = []

    @property
    def state(self) -> PipelineState:
        return self.active_run.state if self.active_run else PipelineState.OFF

    @property
    def active_task_count(self) -> int:
        return sum(
            task is not None and not task.done()
            for task in (self._task, self._operation_task)
        )

    @property
    def pending_approval_count(self) -> int:
        return int(self._approval_waiter is not None)

    def start(self, task: str, workspace: Path) -> PipelineRun:
        run = self._begin(task, workspace)
        try:
            self._read_only_stages(task, workspace)
            self._await("EDIT_PROPOSAL", "Provide a valid patch proposal for review")
        except Exception as error:
            self._fail(error)
        return self.active_run or self.last_run or run

    async def start_async(
        self, task: str, workspace: Path, stage_runner: StageRunner | None = None
    ) -> PipelineRun:
        run = self._begin(task, workspace)
        self._task = asyncio.create_task(
            self._run_async(run.run_id, task, workspace, stage_runner),
            name=f"zeroagent-pipeline-{run.run_id[:12]}",
        )
        await asyncio.sleep(0)
        return self.active_run or self.last_run or run

    async def _run_async(
        self, run_id: str, task: str, workspace: Path, stage_runner: StageRunner | None
    ) -> None:
        try:
            self._require_run(run_id)
            if stage_runner:
                result = stage_runner()
                if inspect.isawaitable(result):
                    await result
                self._require_run(run_id)
            else:
                self._read_only_stages(task, workspace)
            self._require_run(run_id)
            self._await("EDIT_PROPOSAL", "Provide a valid patch proposal for review")
            self._approval_waiter = asyncio.Event()
            await self._approval_waiter.wait()
        except asyncio.CancelledError:
            # cancel_async finalizes exact current run before cancelling this task.
            raise
        except Exception as error:
            if self.active_run and self.active_run.run_id == run_id:
                self._fail(error)
        finally:
            if self._task is asyncio.current_task():
                self._task = None
            self._approval_waiter = None

    async def cancel_async(
        self, detail: str = "Cancellation requested"
    ) -> PipelineRun | None:
        if self._cancellation_lock is None:
            self._cancellation_lock = asyncio.Lock()
        async with self._cancellation_lock:
            return await self._cancel_async_once(detail)

    async def _cancel_async_once(self, detail: str) -> PipelineRun | None:
        if self._operation_task and not self._operation_task.done():
            if self.active_run:
                self.active_run = self.active_run.model_copy(
                    update={
                        "state": PipelineState.CANCELLING,
                        "active_stage": self.active_operation,
                        "awaiting": None,
                        "cancellation_requested": True,
                    }
                )
                self._emit("pipeline cancellation requested", detail)
                self._emit(
                    "pipeline waiting for active operation", self.active_operation or ""
                )
            # Do not cancel asyncio.to_thread: that would detach an active worker.
            try:
                await self._operation_task
            except Exception:
                pass
            return self._cancel(detail)
        run = self._cancel(detail)
        task = self._task
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._approval_waiter = None
        return run

    async def shutdown_async(self) -> PipelineRun | None:
        self._shutdown = True
        return await self.cancel_async("Pipeline shutdown requested")

    def cancel(self, detail: str = "Cancellation requested") -> PipelineRun | None:
        if self._operation_task and not self._operation_task.done():
            raise PipelineError("Active operation requires cancel_async")
        return self._cancel(detail)

    def _cancel(self, detail: str) -> PipelineRun | None:
        if not self.active_run:
            return self.last_run
        run = self.active_run.model_copy(
            update={
                "state": PipelineState.CANCELLED,
                "active_stage": None,
                "awaiting": None,
                "cancellation_requested": True,
                "ended_at": datetime.now(UTC),
            }
        )
        run = self._stage_on(run, "CANCELLED", "CANCELLED", detail)
        self._emit("pipeline cancellation requested", detail)
        self._emit("pipeline cancelled", detail)
        self._finalize(run)
        if self._approval_waiter:
            self._approval_waiter.set()
        return self.last_run

    async def execute_approved_edit_async(
        self, workspace: Path, recovery_root: Path
    ) -> ApplicationResult:
        """Run guarded Apply in owned thread; cancellation waits for settlement."""
        self._claim_operation("APPLY_EDIT", workspace)
        assert self.proposal and self.patch_approval
        self._operation_task = asyncio.create_task(
            asyncio.to_thread(
                apply, self.proposal, self.patch_approval, workspace, recovery_root
            ),
            name="zeroagent-pipeline-apply",
        )
        try:
            result = await self._operation_task
        except Exception as error:
            self._operation_task = None
            self.active_operation = None
            if self.active_run:
                self._stage("APPLY_EDIT", "FAILED", str(error))
                if self.active_run.cancellation_requested:
                    self._cancel("Cancellation requested during Apply")
                else:
                    self._fail(error)
            raise
        self._operation_task = None
        self.active_operation = None
        if self.active_run and self.active_run.cancellation_requested:
            self._record_apply(result)
            self._cancel("Cancellation requested during Apply")
            return result
        return self._finish_apply(result)

    async def execute_approved_test_async(self, workspace: Path) -> TestExecutionResult:
        """Run guarded test in owned thread; cancellation waits for settlement."""
        self._claim_operation("RUN_TEST", workspace)
        assert self.test_spec and self.test_approval
        self._operation_task = asyncio.create_task(
            asyncio.to_thread(
                execute_test, self.test_spec, self.test_approval, workspace
            ),
            name="zeroagent-pipeline-test",
        )
        try:
            result = await self._operation_task
        except Exception as error:
            self._operation_task = None
            self.active_operation = None
            if self.active_run:
                self._stage("RUN_TEST", "FAILED", str(error))
                if self.active_run.cancellation_requested:
                    self._cancel("Cancellation requested during Controlled Test")
                else:
                    self._fail(error)
            raise
        self._operation_task = None
        self.active_operation = None
        if self.active_run and self.active_run.cancellation_requested:
            self._record_test(result)
            self._cancel("Cancellation requested during Controlled Test")
            return result
        return self._finish_test(result, workspace)

    def _begin(self, task: str, workspace: Path) -> PipelineRun:
        if self._shutdown:
            raise PipelineError("Pipeline engine is shut down")
        if self.active_run or self.active_task_count:
            raise PipelineError("A pipeline run is already active")
        root = validate_workspace(workspace)
        if not task.strip():
            raise PipelineError("Pipeline task is required")
        self.active_run = new_run(task, root.name)
        self._workspace = root
        self._applied = False
        self._tested = False
        self.application_result = None
        self.test_result = None
        self.patch_proof = None
        self.test_proof = None
        self._emit("pipeline started", self.active_run.task_summary)
        return self.active_run

    def _read_only_stages(self, task: str, workspace: Path) -> None:
        self.plan = validate_plan(create_plan(task.strip(), workspace))
        self._stage("PLAN", "COMPLETED", "Deterministic plan created")
        self.analysis = analyze_repository(workspace)
        self._stage("ANALYZE", "COMPLETED", f"{self.analysis.file_count} files")

    def submit_proposal(self, proposal: PatchProposal, workspace: Path) -> str:
        self._require_waiting("EDIT_PROPOSAL")
        self._release_waiter()
        self._require_workspace(workspace)
        diff = preview(proposal, workspace)
        self.proposal = proposal
        self._stage("PROPOSE_EDIT", "COMPLETED", f"digest {proposal.digest[:12]}")
        self._await("EDIT_APPROVAL", f"digest {proposal.digest[:12]}")
        return diff

    def approve_edit(self, digest: str, workspace: Path) -> None:
        self._require_waiting("EDIT_APPROVAL")
        self._release_waiter()
        if not self.proposal or digest != self.proposal.digest:
            raise PipelineError("Approval digest does not match current proposal")
        self._require_workspace(workspace)
        self.patch_approval = approve(self.proposal, workspace)
        self._patch_approval_run_id = self._require_active_run_id()
        self._patch_approval_identity = id(self.patch_approval)
        self._stage("APPROVE_EDIT", "COMPLETED", f"digest {digest[:12]}")
        self._await("APPLY_EDIT", "Use Safe Edit Apply for the reviewed proposal")

    def execute_approved_edit(
        self, workspace: Path, recovery_root: Path
    ) -> ApplicationResult:
        """Apply current reviewed proposal once through Safe Edit guard."""
        self._claim_operation("APPLY_EDIT", workspace)
        try:
            result = apply(self.proposal, self.patch_approval, workspace, recovery_root)
        except Exception as error:
            self._stage("APPLY_EDIT", "FAILED", str(error))
            self._fail(error)
            raise
        finally:
            self.active_operation = None
        return self._finish_apply(result)

    def submit_test_spec(self, spec: TestSpecification, workspace: Path) -> None:
        self._require_waiting("TEST_SPECIFICATION")
        self._release_waiter()
        self._require_workspace(workspace)
        self.test_spec = validate_test_spec(spec, workspace)
        self._stage("PROPOSE_TEST", "COMPLETED", f"digest {spec.digest[:12]}")
        self._await("TEST_APPROVAL", f"digest {spec.digest[:12]}")

    def approve_test(self, digest: str, workspace: Path) -> None:
        self._require_waiting("TEST_APPROVAL")
        self._release_waiter()
        if not self.test_spec or digest != self.test_spec.digest:
            raise PipelineError(
                "Approval digest does not match current test specification"
            )
        self._require_workspace(workspace)
        self.test_approval = approve_test_spec(self.test_spec, workspace)
        self._test_approval_run_id = self._require_active_run_id()
        self._test_approval_identity = id(self.test_approval)
        self._stage("APPROVE_TEST", "COMPLETED", f"digest {digest[:12]}")
        self._await("RUN_TEST", "Run reviewed allowlisted test specification")

    def execute_approved_test(self, workspace: Path) -> TestExecutionResult:
        """Run current approved allowlisted test once through Controlled Test."""
        self._claim_operation("RUN_TEST", workspace)
        try:
            result = execute_test(self.test_spec, self.test_approval, workspace)
        except Exception as error:
            self._stage("RUN_TEST", "FAILED", str(error))
            self._fail(error)
            raise
        finally:
            self.active_operation = None
        return self._finish_test(result, workspace)

    def _finish_apply(self, result: ApplicationResult) -> ApplicationResult:
        self._record_apply(result)
        self._await("TEST_SPECIFICATION", "Provide a valid test specification")
        return result

    def _record_apply(self, result: ApplicationResult) -> None:
        self.application_result = result
        self._applied = True
        self._stage("APPLY_EDIT", "EXECUTED", f"{len(result.applied_paths)} paths")
        self._emit("pipeline edit applied", result.proposal_digest[:12])

    def _finish_test(
        self, result: TestExecutionResult, workspace: Path
    ) -> TestExecutionResult:
        self._record_test(result)
        if result.status != "PASSED":
            self._fail(PipelineError(f"Controlled test result: {result.status}"))
            return result
        self._verify_and_complete(workspace)
        return result

    def _record_test(self, result: TestExecutionResult) -> None:
        self.test_result = result
        self._tested = True
        outcome = "EXECUTED" if result.status == "PASSED" else "FAILED"
        self._stage("RUN_TEST", outcome, f"status {result.status}")
        self._emit(
            "pipeline tests passed"
            if result.status == "PASSED"
            else "pipeline tests failed",
            result.status,
        )

    def _claim_operation(self, name: str, workspace: Path) -> None:
        self._require_waiting(name)
        self._release_waiter()
        self._require_workspace(workspace)
        already_executed = self._applied if name == "APPLY_EDIT" else self._tested
        artifact = self.proposal if name == "APPLY_EDIT" else self.test_spec
        approval = self.patch_approval if name == "APPLY_EDIT" else self.test_approval
        if already_executed or not artifact or not approval or self.active_operation:
            raise PipelineError("No unexecuted approved operation is available")
        approval_owner = (
            self._patch_approval_run_id
            if name == "APPLY_EDIT"
            else self._test_approval_run_id
        )
        if approval_owner != self._require_active_run_id():
            raise PipelineError("Approval does not belong to current pipeline run")
        approval_identity = (
            self._patch_approval_identity
            if name == "APPLY_EDIT"
            else self._test_approval_identity
        )
        if id(approval) != approval_identity:
            raise PipelineError("Current approval was replaced after authorization")
        self.active_operation = name
        self._stage(name, "RUNNING", f"digest {artifact.digest[:12]}")

    def _require_active_run_id(self) -> str:
        if not self.active_run:
            raise PipelineError("No active pipeline run")
        return self.active_run.run_id

    def skip_edit(self, reason: str) -> None:
        """Explicitly skip optional edit; report remains incomplete, never applied."""
        self._skip("EDIT", "EDIT_PROPOSAL", reason, "TEST_SPECIFICATION")

    def skip_test(self, reason: str) -> None:
        """Explicitly skip optional tests; report remains incomplete, never passed."""
        self._skip("TEST", "TEST_SPECIFICATION", reason, None)

    def _skip(
        self, stage: str, awaiting: str, reason: str, next_action: str | None
    ) -> None:
        self._require_waiting(awaiting)
        text = " ".join(reason.split())
        if len(text) < 3:
            raise PipelineError("Skip reason must contain at least three characters")
        self._stage(f"SKIP_{stage}", "SKIPPED", text[:400])
        self._skipped_stages.append(stage)
        if next_action:
            self._await(next_action, f"{stage} explicitly skipped")
            return
        run = self.active_run
        assert run
        run = run.model_copy(
            update={"state": PipelineState.COMPLETED, "ended_at": datetime.now(UTC)}
        )
        self._finalize(run)

    def _require_run(self, run_id: str) -> PipelineRun:
        if not self.active_run or self.active_run.run_id != run_id:
            raise PipelineError("Pipeline run is no longer active")
        return self.active_run

    def _require_workspace(self, workspace: Path) -> Path:
        root = validate_workspace(workspace)
        if not self.active_run or self._workspace != root:
            raise PipelineError("Workspace is not bound to current pipeline run")
        return root

    def _release_waiter(self) -> None:
        """Release one engine-owned async approval wait after explicit input."""
        if self._approval_waiter:
            self._approval_waiter.set()

    def _require_waiting(self, awaiting: str) -> PipelineRun:
        run = self.active_run
        if not run or run.state != PipelineState.AWAITING_APPROVAL:
            raise PipelineError("Pipeline is not awaiting input")
        if run.awaiting != awaiting:
            raise PipelineError("Pipeline is awaiting a different action")
        return run

    def _stage(self, name: str, outcome: str, detail: str) -> None:
        if not self.active_run:
            raise PipelineError("No active pipeline run")
        digest = self._operation_digest(name)
        approval = self._approval_digest(name)
        run = self._stage_on(self.active_run, name, outcome, detail, digest, approval)
        self.active_run = run.model_copy(
            update={
                "state": PipelineState.RUNNING,
                "active_stage": name,
                "awaiting": None,
            }
        )
        self._emit("pipeline stage completed", name)

    def _stage_on(
        self,
        run: PipelineRun,
        name: str,
        outcome: str,
        detail: str,
        operation_digest: str | None = None,
        approval_digest: str | None = None,
    ) -> PipelineRun:
        now = datetime.now(UTC)
        stage = StageEvidence(
            name=name,
            outcome=outcome,
            detail=detail[:400],
            started_at=now,
            ended_at=now,
            operation_digest=operation_digest,
            approval_digest=approval_digest,
        )
        return run.model_copy(update={"stages": [*run.stages, stage]})

    def _operation_digest(self, name: str) -> str | None:
        if "EDIT" in name and self.proposal:
            return self.proposal.digest
        if "TEST" in name and self.test_spec:
            return self.test_spec.digest
        return None

    def _approval_digest(self, name: str) -> str | None:
        if name == "APPLY_EDIT" and self.patch_approval:
            return self.patch_approval.proposal_digest
        if name == "RUN_TEST" and self.test_approval:
            return self.test_approval.specification_digest
        return None

    def _verify_and_complete(self, workspace: Path) -> None:
        if not self.proposal or not self.application_result or not self.test_result:
            self._fail(PipelineError("Execution evidence is incomplete"))
            return
        patch_evidence = PatchEvidence(
            proposal_digest=self.proposal.digest,
            approval_bound=True,
            applied_paths=self.application_result.applied_paths,
            recovery_present=Path(
                self.application_result.recovery_path, "manifest.json"
            ).is_file(),
            permissions_preserved=True,
        )
        test_evidence = TestEvidence(
            specification_digest=self.test_result.specification_digest,
            approval_bound=True,
            runner_allowlisted=True,
            execution_completed=True,
            exit_code_zero=self.test_result.exit_code == 0,
            output_integrity=not self.test_result.output_truncated,
        )
        self.patch_proof = verify_execution(None, patch_evidence, workspace)
        self.test_proof = verify_execution(None, test_evidence, workspace)
        self._stage(
            "VERIFY", "COMPLETED", f"test proof {self.test_proof.overall_status}"
        )
        self._emit("pipeline verification completed", self.test_proof.overall_status)
        if self.test_proof.overall_status == "FAILED":
            self._fail(PipelineError("Structural verification failed"))
            return
        if not self.active_run:
            return
        run = self.active_run.model_copy(
            update={
                "state": PipelineState.COMPLETED,
                "active_stage": None,
                "awaiting": None,
                "ended_at": datetime.now(UTC),
            }
        )
        run = self._stage_on(
            run, "COMPLETE", "COMPLETED", "Controlled workflow completed"
        )
        self._emit("pipeline completed", "Controlled workflow completed")
        self._finalize(run)

    def _await(self, awaiting: str, detail: str) -> None:
        if self.active_run:
            self.active_run = self.active_run.model_copy(
                update={
                    "state": PipelineState.AWAITING_APPROVAL,
                    "active_stage": None,
                    "awaiting": awaiting,
                }
            )
            self._emit("pipeline approval requested", detail)

    def _fail(self, error: Exception) -> None:
        if not self.active_run:
            return
        run = self.active_run.model_copy(
            update={
                "state": PipelineState.FAILED,
                "active_stage": None,
                "ended_at": datetime.now(UTC),
                "error_summary": str(error)[:400],
            }
        )
        self._emit("pipeline failed", str(error)[:200])
        self._finalize(self._stage_on(run, "FAILED", "FAILED", str(error)))

    def _finalize(self, run: PipelineRun) -> None:
        self.last_run = run
        proof_status = (
            self.test_proof.overall_status
            if self.test_proof
            else self.patch_proof.overall_status
            if self.patch_proof
            else "INCOMPLETE"
        )
        self.last_report = PipelineReport(
            run=run,
            apply_status=(
                self.application_result.structural_status
                if self.application_result
                else "NOT_EXECUTED"
            ),
            test_status=self.test_result.status if self.test_result else "NOT_EXECUTED",
            proof_status=proof_status,
            skipped_stages=self._skipped_stages,
            cancellation_status=(
                "CANCELLED" if run.state == PipelineState.CANCELLED else "NOT_REQUESTED"
            ),
            limitation=(
                "Structural evidence does not prove semantic code correctness."
                if proof_status == "INCOMPLETE"
                else ""
            ),
        )
        self.active_run = None
        self.proposal = self.patch_approval = None
        self.test_spec = self.test_approval = None
        self._patch_approval_run_id = None
        self._test_approval_run_id = None
        self._patch_approval_identity = None
        self._test_approval_identity = None
        self._workspace = None
        self.active_operation = None

    def _emit(self, title: str, detail: str = "") -> None:
        if self._event_sink:
            try:
                self._event_sink(title, detail[:200], "pipeline")
            except Exception:
                # UI/event delivery must never corrupt guarded lifecycle state.
                pass
