"""Command-line interface for ZEROAGENT X."""

from __future__ import annotations

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
from zeroagent.tui import NeonMinimalTui

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
console = Console()


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
            NeonMinimalTui().run_interactive()
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
) -> None:
    """Launch interactive Neon Minimal terminal interface."""
    interface = NeonMinimalTui(workspace=workspace)
    try:
        interface.run_interactive()
    except RuntimeError as error:
        typer.echo(f"TUI unavailable: {error}", err=True)
        raise typer.Exit(code=2) from error


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
