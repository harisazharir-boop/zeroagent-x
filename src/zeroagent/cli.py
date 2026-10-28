"""Command-line interface for ZEROAGENT X."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from zeroagent import __version__
from zeroagent.ai.models import ProviderError
from zeroagent.ai.service import LocalAIService
from zeroagent.blackbox.history import history as load_history
from zeroagent.blackbox.recorder import Recorder
from zeroagent.blackbox.replay import replay as replay_record
from zeroagent.blackbox.storage import LocalStorage, StorageError
from zeroagent.config import load_settings
from zeroagent.context import (
    ContextError,
    build_context,
    context_prompt,
    inspect_workspace,
    select_context,
)
from zeroagent.core.diagnostics import collect_diagnostics
from zeroagent.core.discovery import DiscoveryLimits
from zeroagent.core.repository import AnalysisReport, analyze_repository
from zeroagent.editing import (
    EditError,
    PatchEvidence,
    PatchProposal,
    approve,
    load_proposal,
    parse_ai_proposal,
    recover,
    validate_proposal,
)
from zeroagent.editing import (
    apply as apply_patch,
)
from zeroagent.editing import (
    preview as preview_patch,
)
from zeroagent.execution.models import ExecutionState
from zeroagent.execution.service import make_coordinator, make_request, request_digest
from zeroagent.planning import (
    PlanError,
    create_plan,
    load_plan,
    validate_plan,
)
from zeroagent.planning import (
    default_registry as default_plan_registry,
)
from zeroagent.proof.engine import verify_execution
from zeroagent.proof.models import ProofReport
from zeroagent.routing.router import RoutingDecision, RoutingError, route_task, run_task
from zeroagent.security.workspace import WorkspaceError
from zeroagent.testing import (
    ALLOWLISTED_RUNNERS,
    TestEvidence,
    TestRunnerError,
    approve_test,
    execute_test,
    load_test_spec,
    make_test_spec,
    validate_test_spec,
)
from zeroagent.textual_app import ZeroAgentApp

app = typer.Typer(
    name="zeroagent",
    help="ZEROAGENT X: local-first, proof-driven agent framework.",
    no_args_is_help=False,
    add_completion=False,
)
ai_app = typer.Typer(
    name="ai",
    help="Explicit optional local Ollama interactions.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(ai_app)
context_app = typer.Typer(
    name="context",
    help="Read-only authorized repository context for local AI questions.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(context_app)
plan_app = typer.Typer(
    name="plan",
    help="Planning-only agent task plans.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(plan_app)
edit_app = typer.Typer(
    name="edit",
    help="Explicit approval-bound safe code editing.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(edit_app)
test_app = typer.Typer(
    name="test",
    help="Explicit allowlisted and approval-bound test execution.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(test_app)
agent_app = typer.Typer(
    name="agent",
    help="Approval-bound external agent execution through ExecutionCoordinator.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(agent_app)
console = Console()


def _agent_payload(result: object) -> str:
    return json.dumps(_json_value(result), indent=2, sort_keys=True)


@agent_app.command("adapters")
def agent_adapters(
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """List registered adapters and local executable availability; never executes."""
    coordinator = make_coordinator()
    rows = []
    for identifier in coordinator.registry.identifiers():
        adapter = coordinator.registry.get(identifier)
        rows.append(
            {
                "identifier": identifier,
                "available": adapter.available(),
                "capabilities": sorted(adapter.capabilities().capabilities),
                "requires_network": adapter.capabilities().requires_network,
            }
        )
    if output_format == "json":
        typer.echo(json.dumps(rows, indent=2))
        return
    for row in rows:
        typer.echo(
            f"{row['identifier']}: {'available' if row['available'] else 'unavailable'}"
        )


@agent_app.command("config")
def agent_config(
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """Show execution policy; credentials and provider config stay hidden."""
    settings = load_settings()
    value = {
        "agent_execution_enabled": settings.agent_execution_enabled,
        "opencode_enabled": settings.opencode_enabled,
        "network_enabled": settings.network_enabled,
        "timeout_seconds": settings.agent_execution_timeout_seconds,
        "max_output_bytes": settings.agent_execution_max_output_bytes,
    }
    typer.echo(
        json.dumps(value, indent=2)
        if output_format == "json"
        else "\n".join(f"{k}: {v}" for k, v in value.items())
    )


def _agent_request_values(
    adapter: str,
    workspace: Path,
    task: str,
    timeout: int | None,
    record: bool,
) -> tuple[str, object]:
    digest = request_digest(
        adapter_id=adapter,
        workspace=workspace,
        prompt=task,
        timeout_seconds=timeout,
        record_evidence=record,
    )
    return digest, make_request(
        adapter_id=adapter,
        workspace=workspace,
        prompt=task,
        timeout_seconds=timeout,
        record_evidence=record,
        approval_digest=None,
    )


@agent_app.command("validate")
def agent_validate(
    task: Annotated[str, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
    adapter: Annotated[str, typer.Option("--adapter")] = "opencode",
    timeout: Annotated[int | None, typer.Option("--timeout", min=1, max=600)] = None,
    record: Annotated[bool, typer.Option("--record")] = False,
) -> None:
    """Show request-bound approval digest. Validation never starts an adapter."""
    digest, request = _agent_request_values(adapter, workspace, task, timeout, record)
    coordinator = make_coordinator()
    try:
        checked = coordinator.registry.get(adapter)
        checked.validate(request)
    except (ValueError, FileNotFoundError) as error:
        typer.echo(f"Agent validation failed: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(
        json.dumps(
            {
                "approval_digest": digest,
                "adapter": adapter,
                "workspace": str(workspace),
                "network_required": checked.capabilities().requires_network,
                "record_evidence": record,
                "timeout_seconds": timeout,
            },
            indent=2,
        )
    )


@agent_app.command("run")
def agent_run(
    task: Annotated[str, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
    approve_digest: Annotated[
        str | None,
        typer.Option("--approve-digest", help="Exact digest from agent validate."),
    ] = None,
    adapter: Annotated[str, typer.Option("--adapter")] = "opencode",
    timeout: Annotated[int | None, typer.Option("--timeout", min=1, max=600)] = None,
    record: Annotated[bool, typer.Option("--record")] = False,
    storage_dir: Annotated[Path | None, typer.Option("--storage-dir")] = None,
) -> None:
    """Run one explicit approved request. Ctrl+C requests bounded adapter cleanup."""
    request = make_request(
        adapter_id=adapter,
        workspace=workspace,
        prompt=task,
        timeout_seconds=timeout,
        record_evidence=record,
        approval_digest=approve_digest,
    )
    coordinator = make_coordinator(storage_dir=storage_dir)
    try:
        result = asyncio.run(coordinator.execute(request))
    except KeyboardInterrupt:
        typer.echo("Cancellation requested before execution completed.", err=True)
        raise typer.Exit(130) from None
    typer.echo(_agent_payload(result))
    if result.state != ExecutionState.SUCCEEDED:
        raise typer.Exit(2)


@agent_app.command("history")
def agent_history(
    limit: Annotated[int, typer.Option(min=1, max=100)] = 20,
    storage_dir: Annotated[Path | None, typer.Option("--storage-dir")] = None,
) -> None:
    """List sanitized recorded agent executions."""
    records = load_history(make_coordinator(storage_dir=storage_dir).storage, limit)
    typer.echo(
        json.dumps([record.model_dump(mode="json") for record in records], indent=2)
    )


@agent_app.command("evidence")
def agent_evidence(
    execution_id: Annotated[str, typer.Argument()],
    storage_dir: Annotated[Path | None, typer.Option("--storage-dir")] = None,
) -> None:
    """Inspect sanitized evidence by ID; this command never retries work."""
    try:
        record = make_coordinator(storage_dir=storage_dir).storage.load(execution_id)
    except StorageError as error:
        typer.echo(f"Evidence failed: {error}", err=True)
        raise typer.Exit(2) from error
    typer.echo(record.model_dump_json(indent=2))


@agent_app.command("status")
def agent_status(
    execution_id: Annotated[str, typer.Argument(help="Recorded evidence ID.")],
    storage_dir: Annotated[Path | None, typer.Option("--storage-dir")] = None,
) -> None:
    """Show terminal recorded status; active cross-process status is unsupported."""
    agent_evidence(execution_id, storage_dir)


@agent_app.command("cancel")
def agent_cancel(execution_id: Annotated[str, typer.Argument()]) -> None:
    """Explain CLI cancellation boundary; use Ctrl+C in owning `agent run` process."""
    typer.echo(
        f"Cannot cancel {execution_id}: cross-process cancellation is unsupported. "
        "Use Ctrl+C in process that started agent run.",
        err=True,
    )
    raise typer.Exit(2)


def version_callback(value: bool) -> None:
    """Print version and exit before command parsing continues."""
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root(
    context: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        help="Show ZEROAGENT X version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """ZEROAGENT X: local-first, proof-driven agent framework."""
    if context.invoked_subcommand is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            ZeroAgentApp().run()
        else:
            typer.echo(context.get_help())


@app.command()
def doctor() -> None:
    """Show current runtime and safe-default configuration diagnostics."""
    settings = load_settings()
    values = collect_diagnostics(settings)
    diagnostics = Table(title="ZEROAGENT X diagnostics", show_header=False)
    diagnostics.add_column("Name", style="bold cyan")
    diagnostics.add_column("Value")
    diagnostics.add_row("Version", values["version"])
    diagnostics.add_row("Python", values["python"])
    diagnostics.add_row("Platform", values["platform"])
    diagnostics.add_row("Current directory", values["current_directory"])
    diagnostics.add_row("Telemetry", values["telemetry"])
    diagnostics.add_row("Network access", values["network_access"])
    diagnostics.add_row("Shell command execution", values["shell_command_execution"])
    console.print(diagnostics)


@app.command()
def tui(
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", help="Initial workspace for TUI actions."),
    ] = None,
    debug: Annotated[
        bool,
        typer.Option("--debug", help="Enable TUI startup diagnostics."),
    ] = False,
    no_logo: Annotated[
        bool,
        typer.Option("--no-logo", help="Disable inline graphics logo rendering."),
    ] = False,
) -> None:
    """Launch full-screen ZEROAGENT X Agent Workspace."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        typer.echo("TUI requires an interactive terminal.", err=True)
        raise typer.Exit(code=2)
    ZeroAgentApp(workspace=workspace, debug_mode=debug, enable_logo=not no_logo).run()


def _ai_service() -> LocalAIService:
    """Dedicated AI commands explicitly authorize validated loopback communication."""
    return LocalAIService(load_settings())


def _render_context(report) -> None:
    table = Table(title="Repository context selection")
    table.add_column("Path")
    table.add_column("Score", justify="right")
    table.add_column("Reasons")
    for selection in report.selections:
        table.add_row(
            selection.path, str(selection.score), ", ".join(selection.reasons)
        )
    console.print(table)
    console.print(f"Sources read: {len(report.sources)} · Bytes: {report.total_bytes}")
    if report.exclusions:
        console.print(f"[yellow]Exclusions/warnings:[/yellow] {len(report.exclusions)}")


def _render_plan(plan) -> None:
    console.print(f"[bold cyan]TASK PLAN[/bold cyan]\n{plan.task}")
    table = Table(title=f"Plan status: {plan.status}")
    table.add_column("Step")
    table.add_column("Tool")
    table.add_column("Permissions")
    table.add_column("Availability")
    for step in plan.steps:
        table.add_row(
            step.description, step.tool, ", ".join(step.permissions), step.availability
        )
    console.print(table)
    console.print("[yellow]Planning only. No tools were executed.[/yellow]")


def _load_proposal(path: Path) -> PatchProposal:
    return load_proposal(path)


@edit_app.command("validate")
def edit_validate(
    proposal_file: Annotated[Path, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
) -> None:
    """Validate structured patch proposal without modifying files."""
    try:
        proposal = validate_proposal(_load_proposal(proposal_file), workspace)
    except (EditError, WorkspaceError) as error:
        typer.echo(f"Edit validation failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    console.print(
        f"[green]Valid proposal {proposal.digest}. No files modified.[/green]"
    )


@edit_app.command("propose")
def edit_propose(
    task: Annotated[str, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
    model: Annotated[str, typer.Option("--model")],
    allow_context: Annotated[bool, typer.Option("--allow-context")] = False,
) -> None:
    """Request untrusted structured patch JSON from local model; never write."""
    try:
        report = build_context(workspace, task, allow_context=allow_context)
        if not report.sources:
            raise ContextError("No safe relevant source excerpts available")
        prompt = (
            context_prompt(report) + "\nReturn JSON with changes and explanation only."
        )
        proposal = parse_ai_proposal(
            _ai_service().ask(prompt, model).response, workspace
        )
    except (
        ContextError,
        EditError,
        ProviderError,
        ValueError,
        WorkspaceError,
    ) as error:
        typer.echo(f"Edit propose failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(proposal.model_dump_json(indent=2))
    console.print("[yellow]Proposal created. No repository files modified.[/yellow]")


@edit_app.command("preview")
def edit_preview(
    proposal_file: Annotated[Path, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
) -> None:
    """Show validated patch content metadata without modifying files."""
    try:
        proposal = validate_proposal(_load_proposal(proposal_file), workspace)
    except (EditError, WorkspaceError) as error:
        typer.echo(f"Edit preview failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    console.print(f"Proposal digest: [cyan]{proposal.digest}[/cyan]")
    for change in proposal.changes:
        console.print(f"[cyan]{change.operation}[/cyan] {change.path}")
        console.print(f"Original: {change.original_sha256 or '<new file>'}")
        console.print(f"Result: {change.resulting_sha256}")
    console.print(preview_patch(proposal, workspace), markup=False, highlight=False)
    console.print("[yellow]No tests ran. Preview does not modify files.[/yellow]")


@edit_app.command("apply")
def edit_apply(
    proposal_file: Annotated[Path, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
    approve_digest: Annotated[
        str,
        typer.Option(
            "--approve-digest", help="Exact proposal digest shown by preview."
        ),
    ],
    recovery_dir: Annotated[Path, typer.Option("--recovery-dir")],
    record: Annotated[
        bool, typer.Option("--record", help="Record sanitized edit metadata.")
    ] = False,
    storage_dir: Annotated[Path | None, typer.Option("--storage-dir")] = None,
) -> None:
    """Apply exact validated proposal only with explicit digest approval."""
    try:
        proposal = _load_proposal(proposal_file)
        approval = approve(proposal, workspace)
        if approve_digest != approval.proposal_digest:
            raise EditError("Approval digest does not match proposal")
        result = apply_patch(proposal, approval, workspace, recovery_dir)
    except (EditError, WorkspaceError) as error:
        typer.echo(f"Edit apply failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    evidence = PatchEvidence(
        proposal_digest=proposal.digest,
        approval_bound=True,
        applied_paths=result.applied_paths,
        recovery_present=True,
        permissions_preserved=True,
    )
    proof = verify_execution(None, evidence, workspace)
    audit = "not_requested"
    if record:
        recorder = Recorder("safe_edit_application")
        recorder.emit(
            "edit_application",
            {
                "proposal_id": proposal.proposal_id,
                "proposal_digest": proposal.digest,
                "operation_count": len(proposal.changes),
                "approval_status": "approved",
                "application_status": result.structural_status,
                "proof_status": proof.overall_status,
                "recovery_reference": result.recovery_path,
            },
        )
        try:
            _storage(storage_dir).save(
                recorder.build(
                    status="SUCCEEDED",
                    capability_identifier="code.apply",
                    task_category="safe_edit",
                    result_summary={
                        "proposal_digest": proposal.digest,
                        "file_count": len(result.applied_paths),
                    },
                    proof_summary={"overall_status": proof.overall_status},
                )
            )
            audit = "recorded"
        except StorageError as error:
            audit = f"failed: {error}"
    typer.echo(
        json.dumps(
            {
                "application": result.model_dump(),
                "proof": proof.model_dump(),
                "audit": audit,
            },
            indent=2,
        )
    )


@edit_app.command("recover")
def edit_recover(
    recovery_dir: Annotated[Path, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
) -> None:
    """Explicitly restore an application only if edited files remain unchanged."""
    try:
        typer.echo(
            json.dumps({"restored_paths": recover(recovery_dir, workspace)}, indent=2)
        )
    except (EditError, WorkspaceError) as error:
        typer.echo(f"Edit recovery failed: {error}", err=True)
        raise typer.Exit(code=2) from error


@test_app.command("runners")
def test_runners(
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """List strictly allowlisted test runners."""
    if output_format == "json":
        typer.echo(json.dumps(list(ALLOWLISTED_RUNNERS), indent=2))
        return
    table = Table(title="Allowlisted test runners")
    table.add_column("Runner")
    table.add_column("Command Target")
    for r in ALLOWLISTED_RUNNERS:
        table.add_row(r, f"{sys.executable} -m {r}")
    console.print(table)


@test_app.command("create")
def test_create(
    workspace: Annotated[Path, typer.Option("--workspace")],
    runner: Annotated[str, typer.Option("--runner")] = "pytest",
    args: Annotated[
        str, typer.Option("--args", help="Arguments separated by spaces")
    ] = "",
    timeout: Annotated[int, typer.Option("--timeout")] = 30,
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """Create a new test specification without executing."""
    arg_list = [a for a in args.split(" ") if a]
    try:
        spec = make_test_spec(
            workspace=workspace,
            runner=runner,
            arguments=arg_list,
            timeout_seconds=timeout,
        )
    except (TestRunnerError, WorkspaceError) as error:
        typer.echo(f"Test creation failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    if output_format == "json":
        typer.echo(spec.model_dump_json(indent=2))
    else:
        console.print(
            f"[bold cyan]TEST SPECIFICATION CREATED[/bold cyan]: {spec.digest}"
        )
        console.print(f"Runner: {spec.runner}")
        console.print(f"Arguments: {spec.arguments}")
        console.print(f"Timeout: {spec.timeout_seconds}s")
        console.print("[yellow]Specification created. No tests were executed.[/yellow]")


@test_app.command("validate")
def test_validate(
    spec_file: Annotated[Path, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """Validate a test specification against allowlist and workspace rules."""
    try:
        spec = load_test_spec(spec_file)
        validated = validate_test_spec(spec, workspace)
    except (TestRunnerError, WorkspaceError) as error:
        typer.echo(f"Test validation failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    if output_format == "json":
        typer.echo(validated.model_dump_json(indent=2))
    else:
        console.print(
            f"[green]Valid test specification {validated.digest}. No tests run.[/green]"
        )


@test_app.command("preview")
def test_preview(
    spec_file: Annotated[Path, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
) -> None:
    """Preview the exact command and digest that would be run upon approval."""
    try:
        spec = load_test_spec(spec_file)
        validated = validate_test_spec(spec, workspace)
    except (TestRunnerError, WorkspaceError) as error:
        typer.echo(f"Test preview failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    console.print(f"Specification digest: [cyan]{validated.digest}[/cyan]")
    console.print(
        f"Runner: {validated.runner} ({sys.executable} -m {validated.runner})"
    )
    console.print(f"Arguments: {validated.arguments}")
    console.print(f"Timeout: {validated.timeout_seconds}s")
    console.print(
        "[yellow]Notice: Pytest executes repository code. "
        "Exact approval required before run.[/yellow]"
    )


@test_app.command("run")
def test_run(
    spec_file: Annotated[Path, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
    approve_digest: Annotated[
        str,
        typer.Option(
            "--approve-digest", help="Exact specification digest shown by preview."
        ),
    ],
    record: Annotated[
        bool, typer.Option("--record", help="Record sanitized test audit metadata.")
    ] = False,
    storage_dir: Annotated[Path | None, typer.Option("--storage-dir")] = None,
) -> None:
    """Execute allowlisted test specification only with exact digest approval."""
    try:
        spec = load_test_spec(spec_file)
        approval = approve_test(spec, workspace)
        if approve_digest != approval.specification_digest:
            raise TestRunnerError("Approval digest does not match test specification")
        result = execute_test(spec, approval, workspace)
    except (TestRunnerError, WorkspaceError) as error:
        typer.echo(f"Test run failed: {error}", err=True)
        raise typer.Exit(code=2) from error

    evidence = TestEvidence(
        specification_digest=spec.digest,
        approval_bound=True,
        runner_allowlisted=spec.runner in ALLOWLISTED_RUNNERS,
        execution_completed=result.status in ("PASSED", "FAILED"),
        exit_code_zero=result.exit_code == 0,
        output_integrity=not result.output_truncated,
    )
    proof = verify_execution(None, evidence, workspace)

    audit = "not_requested"
    if record:
        recorder = Recorder("test_execution")
        recorder.emit(
            "test_execution",
            {
                "specification_id": spec.specification_id,
                "specification_digest": spec.digest,
                "runner": spec.runner,
                "approval_status": "approved",
                "execution_status": result.status,
                "exit_code": result.exit_code,
                "proof_status": proof.overall_status,
            },
        )
        try:
            _storage(storage_dir).save(
                recorder.build(
                    status="SUCCEEDED" if result.status == "PASSED" else "FAILED",
                    capability_identifier="tests.execute",
                    task_category="test_execution",
                    result_summary={
                        "specification_digest": spec.digest,
                        "runner": spec.runner,
                        "exit_code": result.exit_code,
                        "duration_seconds": result.duration_seconds,
                    },
                    proof_summary={"overall_status": proof.overall_status},
                )
            )
            audit = "recorded"
        except StorageError as err:
            audit = f"failed: {err}"

    typer.echo(
        json.dumps(
            {
                "result": result.model_dump(),
                "proof": proof.model_dump(),
                "audit": audit,
            },
            indent=2,
        )
    )
    if result.status != "PASSED":
        raise typer.Exit(code=1)


@plan_app.command("tools")
def plan_tools(
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """List static capability catalog; listing never executes tools."""
    tools = default_plan_registry().all()
    if output_format == "json":
        typer.echo(json.dumps([tool.model_dump() for tool in tools], indent=2))
        return
    table = Table(title="Planning tool registry")
    table.add_column("Tool")
    table.add_column("Permissions")
    table.add_column("Status")
    for tool in tools:
        table.add_row(
            tool.identifier, ", ".join(tool.permissions), tool.implementation_status
        )
    console.print(table)


@plan_app.command("create")
def plan_create(
    task: Annotated[str, typer.Argument()],
    workspace: Annotated[Path, typer.Option("--workspace")],
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """Create and validate deterministic plan without execution."""
    try:
        plan = validate_plan(create_plan(task, workspace))
    except (PlanError, WorkspaceError) as error:
        typer.echo(f"Plan create failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(plan.model_dump_json(indent=2))
    else:
        _render_plan(plan)


@plan_app.command("validate")
def plan_validate(
    plan_file: Annotated[Path, typer.Argument()],
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """Validate untrusted plan JSON against static registry without execution."""
    try:
        plan = validate_plan(load_plan(plan_file))
    except PlanError as error:
        typer.echo(f"Plan validation failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(plan.model_dump_json(indent=2))
    else:
        console.print("[green]Plan structurally valid. No tools were executed.[/green]")


@context_app.command("inspect")
def context_inspect(
    workspace: Annotated[
        Path, typer.Option("--workspace", help="Repository workspace.")
    ],
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """Show safe context candidates without reading source content."""
    try:
        report = inspect_workspace(workspace)
    except WorkspaceError as error:
        typer.echo(f"Context inspect failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(report.model_dump_json(indent=2))
    else:
        _render_context(report)


@context_app.command("preview")
def context_preview(
    question: Annotated[
        str, typer.Argument(help="Repository question for deterministic selection.")
    ],
    workspace: Annotated[
        Path, typer.Option("--workspace", help="Repository workspace.")
    ],
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """Preview selected paths and reasons without reading source content."""
    try:
        report = select_context(workspace, question)
    except (WorkspaceError, ContextError) as error:
        typer.echo(f"Context preview failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(report.model_dump_json(indent=2))
    else:
        _render_context(report)


@context_app.command("ask")
def context_ask(
    question: Annotated[
        str, typer.Argument(help="Question about authorized repository context.")
    ],
    workspace: Annotated[
        Path, typer.Option("--workspace", help="Repository workspace.")
    ],
    model: Annotated[
        str, typer.Option("--model", help="Installed local Ollama model.")
    ],
    allow_context: Annotated[
        bool,
        typer.Option(
            "--allow-context",
            help="Authorize reading and sending bounded source excerpts.",
        ),
    ] = False,
    output_format: Annotated[str, typer.Option("--format")] = "text",
) -> None:
    """Ask selected local model about authorized bounded repository context."""
    try:
        report = build_context(workspace, question, allow_context=allow_context)
        if not report.sources:
            raise ContextError("No safe relevant source excerpts available")
        response = _ai_service().ask(context_prompt(report), model)
    except (WorkspaceError, ContextError, ProviderError, ValueError) as error:
        typer.echo(f"Context ask failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    references = [
        f"{source.path}:{source.start_line}-{source.end_line}"
        for source in report.sources
    ]
    if output_format == "json":
        typer.echo(
            json.dumps(
                {
                    "answer": response.response,
                    "sources": references,
                    "context": report.model_dump(),
                },
                indent=2,
            )
        )
    else:
        console.print(response.response)
        console.print("[bold cyan]Sources supplied:[/bold cyan]")
        for reference in references:
            console.print(f"- {reference}")


@ai_app.command("doctor")
def ai_doctor(
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
) -> None:
    """Contact configured local Ollama endpoint and report provider diagnostics."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    try:
        info = _ai_service().doctor()
    except ProviderError as error:
        typer.echo(f"AI doctor failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(info.model_dump_json(indent=2))
    else:
        console.print(f"Provider: {info.provider_id}")
        console.print(f"Endpoint: {info.endpoint}")
        console.print(f"Reachable: {'yes' if info.reachable else 'no'}")
        if info.model_count is not None:
            console.print(f"Models: {info.model_count}")
        if info.error_message:
            console.print(f"Failure: {info.error_message}")
    if not info.reachable:
        raise typer.Exit(code=2)


@ai_app.command("models")
def ai_models(
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
) -> None:
    """List models actually returned by configured local Ollama service."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    try:
        models = _ai_service().models()
    except ProviderError as error:
        typer.echo(f"AI models failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        import json

        typer.echo(json.dumps([model.model_dump() for model in models], indent=2))
        return
    if not models:
        console.print("No installed Ollama models.")
        return
    table = Table(title="Installed Ollama models")
    table.add_column("Model")
    table.add_column("Size", justify="right")
    for model in models:
        table.add_row(model.identifier, str(model.size_bytes or "-"))
    console.print(table)


@ai_app.command("ask")
def ai_ask(
    prompt: Annotated[
        str, typer.Argument(help="Explicit text prompt sent to local Ollama.")
    ],
    model: Annotated[
        str, typer.Option("--model", help="Installed Ollama model identifier.")
    ],
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
) -> None:
    """Generate text with explicitly selected installed local Ollama model."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    try:
        response = _ai_service().ask(prompt, model)
    except (ProviderError, ValueError) as error:
        typer.echo(f"AI ask failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(response.model_dump_json(indent=2))
    else:
        console.print(response.response)


def _render_report(report: AnalysisReport) -> None:
    console.print(f"[bold]Workspace:[/bold] {report.workspace_identifier}")
    console.print(f"[bold]Files:[/bold] {report.file_count}")
    console.print(f"[bold]Directories:[/bold] {report.directory_count}")
    console.print(f"[bold]Complete:[/bold] {'yes' if report.complete else 'no'}")
    languages = Table(title="Languages (file-count metric)")
    languages.add_column("Language")
    languages.add_column("Files", justify="right")
    languages.add_column("Percent", justify="right")
    for language in report.languages:
        languages.add_row(
            language.language, str(language.file_count), f"{language.percentage:.2f}%"
        )
    console.print(languages)
    if report.ecosystems:
        console.print(f"[bold]Ecosystems:[/bold] {', '.join(report.ecosystems)}")
    if report.manifests:
        console.print(f"[bold]Manifests:[/bold] {', '.join(report.manifests)}")
    if report.warnings:
        console.print(f"[yellow]Warnings:[/yellow] {len(report.warnings)}")


@app.command()
def analyze(
    workspace: Annotated[Path, typer.Argument(help="Directory to analyze read-only.")],
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
    output: Annotated[
        Path | None, typer.Option("--output", help="New JSON report file destination.")
    ] = None,
    max_files: Annotated[
        int, typer.Option(min=1, help="Maximum discovered files.")
    ] = 10_000,
    max_file_size: Annotated[
        int, typer.Option(min=1, help="Maximum included file size in bytes.")
    ] = 5_000_000,
    max_depth: Annotated[
        int, typer.Option(min=0, help="Maximum directory depth.")
    ] = 20,
) -> None:
    """Analyze explicit workspace without executing repository code."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    try:
        report = analyze_repository(
            workspace,
            DiscoveryLimits(
                max_files=max_files,
                max_file_size_bytes=max_file_size,
                max_directory_depth=max_depth,
            ),
        )
    except WorkspaceError as error:
        typer.echo(f"Analysis failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    serialized = report.model_dump_json(indent=2)
    if output:
        try:
            with output.open("x", encoding="utf-8") as report_file:
                report_file.write(serialized)
                report_file.write("\n")
        except FileExistsError as error:
            typer.echo(f"Analysis failed: Output already exists: {output}", err=True)
            raise typer.Exit(code=2) from error
        except OSError as error:
            typer.echo(f"Analysis failed: Cannot write output: {error}", err=True)
            raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(serialized)
    else:
        _render_report(report)


def _render_decision(decision: RoutingDecision) -> None:
    console.print(f"[bold]Task category:[/bold] {decision.classification.category}")
    console.print(f"[bold]Decision:[/bold] {decision.decision}")
    console.print(f"[bold]Reason:[/bold] {decision.reason}")
    if decision.selected_capability:
        console.print(f"[bold]Capability:[/bold] {decision.selected_capability}")
    console.print(
        f"[bold]Execution performed:[/bold] "
        f"{'yes' if decision.execution_performed else 'no'}"
    )


def _render_proof(proof: ProofReport) -> None:
    console.print(f"[bold]Verification status:[/bold] {proof.overall_status}")
    checks = Table(title="Proof checks")
    checks.add_column("Check")
    checks.add_column("Status")
    checks.add_column("Required")
    checks.add_column("Reason")
    for check in proof.checks:
        checks.add_row(check.check_id, check.status, str(check.required), check.reason)
    console.print(checks)


def _json_value(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")  # type: ignore[union-attr]
    return value


def _storage(storage_dir: Path | None) -> LocalStorage:
    settings = load_settings()
    root = storage_dir or (
        Path(settings.blackbox_storage_dir) if settings.blackbox_storage_dir else None
    )
    return LocalStorage(
        root,
        max_records=settings.blackbox_max_records,
        max_record_bytes=settings.blackbox_max_record_bytes,
        max_age_days=settings.blackbox_max_record_age_days,
    )


def _result_summary(result: object) -> dict[str, object]:
    if isinstance(result, AnalysisReport):
        return {
            "artifact_type": "repository_report",
            "workspace_identifier": result.workspace_identifier,
            "file_count": result.file_count,
            "directory_count": result.directory_count,
            "complete": result.complete,
        }
    return {"artifact_type": type(result).__name__}


def _proof_summary(proof: ProofReport | None) -> dict[str, object] | None:
    if proof is None:
        return None
    return {
        "overall_status": proof.overall_status,
        "checks": [
            {"check_id": check.check_id, "status": check.status, "reason": check.reason}
            for check in proof.checks
        ],
    }


def _render_history(records: list[object]) -> None:
    if not records:
        console.print("No recorded executions.")
        return
    table = Table(title="AgentBlackBox history")
    table.add_column("Execution ID")
    table.add_column("Started")
    table.add_column("Capability")
    table.add_column("Status")
    table.add_column("Proof")
    for record in records:
        proof = record.proof_summary or {}
        table.add_row(
            record.execution_id,
            record.started_at.isoformat(),
            record.capability_identifier or "-",
            record.status,
            str(proof.get("overall_status", "-")),
        )
    console.print(table)


def _render_record(record: object, *, replay: bool = False) -> None:
    if replay:
        console.print(
            "[bold yellow]Historical replay. No capability was executed.[/bold yellow]"
        )
    console.print(f"[bold]Execution ID:[/bold] {record.execution_id}")
    console.print(f"[bold]Status:[/bold] {record.status}")
    console.print(f"[bold]Capability:[/bold] {record.capability_identifier or '-'}")
    console.print(f"[bold]Task category:[/bold] {record.task_category or '-'}")
    events = Table(title="Recorded events")
    events.add_column("Sequence")
    events.add_column("Event")
    events.add_column("Timestamp")
    for event in record.events:
        events.add_row(
            str(event.sequence), event.event_type, event.timestamp.isoformat()
        )
    console.print(events)
    if record.proof_summary:
        console.print(
            f"[bold]Proof:[/bold] {record.proof_summary.get('overall_status', '-')}"
        )
    console.print(
        "[dim]Records are sanitized local history, not cryptographic evidence.[/dim]"
    )


@app.command()
def route(
    task: Annotated[
        str, typer.Argument(help="Task instruction to route without execution.")
    ],
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
) -> None:
    """Show local routing decision without executing a capability."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    decision, _ = route_task(task)
    if output_format == "json":
        typer.echo(decision.model_dump_json(indent=2))
    else:
        _render_decision(decision)
    if decision.decision != "allowed":
        raise typer.Exit(code=2)


@app.command()
def run(
    task: Annotated[
        str, typer.Argument(help="Supported task instruction to execute locally.")
    ],
    workspace: Annotated[
        Path | None,
        typer.Option("--workspace", help="Explicit workspace for repository tasks."),
    ] = None,
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
    verify: Annotated[
        bool,
        typer.Option("--verify", help="Verify actual result against explicit checks."),
    ] = False,
    record: Annotated[
        bool,
        typer.Option("--record", help="Persist sanitized local execution history."),
    ] = False,
    storage_dir: Annotated[
        Path | None,
        typer.Option("--storage-dir", help="Local BlackBox storage override."),
    ] = None,
) -> None:
    """Execute only policy-permitted registered local capability."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    recorder = Recorder(task) if record else None

    def observer(event_type: str, details: dict[str, object]) -> None:
        if recorder:
            recorder.emit(event_type, details)

    try:
        decision, result = run_task(task, workspace, observer=observer)
    except (RoutingError, WorkspaceError) as error:
        if recorder:
            failed_record = recorder.build(
                status="FAILED", error=str(error), complete=False
            )
            try:
                _storage(storage_dir).save(failed_record)
            except StorageError as storage_error:
                typer.echo(f"Recording failed: {storage_error}", err=True)
            else:
                typer.echo(
                    f"Recorded execution: {failed_record.execution_id}", err=True
                )
        typer.echo(f"Run failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if recorder and verify:
        recorder.emit("verification_started")
    proof = verify_execution(decision, result, workspace) if verify else None
    if recorder and proof:
        recorder.emit("verification_completed", {"status": proof.overall_status})
    execution_id: str | None = None
    if recorder:
        completed_record = recorder.build(
            status="SUCCEEDED",
            capability_identifier=decision.selected_capability,
            task_category=decision.classification.category,
            routing=decision.model_dump(mode="json"),
            result_summary=_result_summary(result),
            proof_summary=_proof_summary(proof),
        )
        try:
            _storage(storage_dir).save(completed_record)
            execution_id = completed_record.execution_id
        except StorageError as error:
            typer.echo(f"Recording failed: {error}", err=True)
    if output_format == "json":
        import json

        payload = {
            "routing": decision.model_dump(mode="json"),
            "result": _json_value(result),
        }
        if proof:
            payload["proof"] = proof.model_dump(mode="json")
        if execution_id:
            payload["execution_id"] = execution_id
        typer.echo(
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _render_decision(decision)
        if isinstance(result, AnalysisReport):
            _render_report(result)
        else:
            console.print_json(data=_json_value(result))
        if proof:
            _render_proof(proof)
        if execution_id:
            console.print(f"[bold]Recorded execution:[/bold] {execution_id}")
    if proof and proof.overall_status == "FAILED":
        raise typer.Exit(code=3)
    if proof and proof.overall_status == "INCOMPLETE":
        raise typer.Exit(code=4)


@app.command()
def history(
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
    limit: Annotated[
        int, typer.Option(min=1, max=100, help="Maximum records to show.")
    ] = 20,
    storage_dir: Annotated[
        Path | None,
        typer.Option("--storage-dir", help="Local BlackBox storage override."),
    ] = None,
) -> None:
    """Show local BlackBox history without executing recorded work."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    try:
        records = load_history(_storage(storage_dir), limit)
    except StorageError as error:
        typer.echo(f"History failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        import json

        typer.echo(
            json.dumps([item.model_dump(mode="json") for item in records], indent=2)
        )
    else:
        _render_history(records)


@app.command()
def inspect(
    execution_id: Annotated[str, typer.Argument(help="Recorded execution ID.")],
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
    storage_dir: Annotated[
        Path | None,
        typer.Option("--storage-dir", help="Local BlackBox storage override."),
    ] = None,
) -> None:
    """Inspect a stored execution record without executing it."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    try:
        stored = _storage(storage_dir).load(execution_id)
    except StorageError as error:
        typer.echo(f"Inspect failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(stored.model_dump_json(indent=2))
    else:
        _render_record(stored)


@app.command()
def replay(
    execution_id: Annotated[str, typer.Argument(help="Recorded execution ID.")],
    output_format: Annotated[
        str, typer.Option("--format", help="Output format: text or json.")
    ] = "text",
    storage_dir: Annotated[
        Path | None,
        typer.Option("--storage-dir", help="Local BlackBox storage override."),
    ] = None,
) -> None:
    """Display historical record events without rerunning a capability."""
    if output_format not in {"text", "json"}:
        raise typer.BadParameter("must be 'text' or 'json'", param_hint="--format")
    try:
        stored = replay_record(_storage(storage_dir).load(execution_id))
    except StorageError as error:
        typer.echo(f"Replay failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    if output_format == "json":
        typer.echo(stored.model_dump_json(indent=2))
    else:
        _render_record(stored, replay=True)


def main() -> None:
    """Run CLI and preserve Typer's process exit status."""
    try:
        app()
    except BrokenPipeError:
        sys.exit(1)
