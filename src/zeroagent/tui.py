"""ZEROAGENT X Neon Minimal terminal interface using Rich only."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from zeroagent import __version__
from zeroagent.ai.models import InstalledModel, ProviderError
from zeroagent.ai.service import LocalAIService
from zeroagent.blackbox.history import history
from zeroagent.blackbox.replay import replay
from zeroagent.blackbox.storage import LocalStorage, StorageError
from zeroagent.config import load_settings
from zeroagent.core.repository import AnalysisReport, analyze_repository
from zeroagent.proof.engine import verify_execution
from zeroagent.routing.router import RoutingError, run_task
from zeroagent.security.workspace import WorkspaceError

CYAN = "#00E5FF"
PURPLE = "#A855F7"
GREEN = "#34D399"
MUTED = "#94A3B8"
RED = "#FB7185"
TEXT = "#F8FAFC"
CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
MENU = (
    "Analyze Repository",
    "Run Local Agent",
    "Verify Execution",
    "Execution History",
    "Historical Replay",
    "Local AI Chat",
    "Settings",
)


@dataclass
class TuiState:
    workspace: Path = field(default_factory=Path.cwd)
    selected: int = 0
    screen: str = "home"
    message: str = "Ready. Select action, type a number, or press / for command mode."
    last_report: AnalysisReport | None = None
    history_records: list[object] = field(default_factory=list)
    history_selected: int = 0
    ai_models: list[InstalledModel] = field(default_factory=list)
    ai_selected: int = 0
    ai_response: str | None = None


def safe_terminal_text(value: object, limit: int = 4_000) -> str:
    """Bound untrusted terminal text and remove control sequences before rendering."""
    return CONTROL_CHARACTERS.sub("?", str(value))[:limit]


class NeonMinimalTui:
    """Small stateful Rich TUI; all actions call existing local services."""

    def __init__(
        self, console: Console | None = None, workspace: Path | None = None
    ) -> None:
        self.console = console or Console()
        self.state = TuiState(workspace=workspace or Path.cwd())

    def render(self) -> None:
        width = self.console.size.width
        if width < 55:
            self._render_narrow()
            return
        self.console.clear()
        self.console.print(self._header(compact=width < 90))
        self.console.print(self._body())
        self.console.print(
            Align.center(
                Text(
                    "LOCAL-FIRST · PROOF-DRIVEN · ZERO PAID API REQUIRED", style=PURPLE
                )
            )
        )

    def _header(self, compact: bool) -> Panel:
        logo = "ZERO" if compact else "Z E R O"
        title = Text()
        title.append(f"{logo}\n", style=f"bold {CYAN}")
        title.append("AGENT X", style=f"bold {PURPLE}")
        title.append(f"  v{__version__}\n", style=MUTED)
        title.append("Don't Just Run AI. Prove It Works.", style=TEXT)
        return Panel(Align.center(title), border_style=CYAN, padding=(0, 2))

    def _body(self) -> Panel:
        if self.state.screen == "home":
            table = Table.grid(expand=True)
            table.add_column(ratio=1)
            table.add_column(ratio=2)
            table.add_row(self._status(), self._menu())
            content: object = table
        else:
            content = self._screen_content()
        return Panel(
            content,
            title=f"[bold {PURPLE}]{self.state.screen.upper()}[/]",
            border_style=PURPLE,
        )

    def _status(self) -> Panel:
        settings = load_settings()
        status = Text()
        status.append("WORKSPACE\n", style=f"bold {CYAN}")
        status.append(f"{safe_terminal_text(self.state.workspace)}\n\n", style=TEXT)
        status.append("ENGINE STATUS\n", style=f"bold {CYAN}")
        status.append("Deterministic engine online\n", style=GREEN)
        status.append(
            "Network disabled\n"
            if not settings.network_enabled
            else "Network enabled\n",
            style=MUTED,
        )
        status.append(
            "Telemetry disabled\n"
            if not settings.telemetry_enabled
            else "Telemetry enabled\n",
            style=MUTED,
        )
        return Panel(status, border_style=MUTED)

    def _menu(self) -> Panel:
        menu = Text("QUICK ACTIONS\n", style=f"bold {CYAN}")
        for index, item in enumerate(MENU, start=1):
            marker = "❯" if index - 1 == self.state.selected else " "
            style = f"bold {PURPLE}" if index - 1 == self.state.selected else TEXT
            menu.append(f"{marker} {index}. {item}\n", style=style)
        menu.append("\n↑/↓ select · Enter run · / command · q quit", style=MUTED)
        return Panel(menu, border_style=PURPLE)

    def _screen_content(self) -> object:
        if self.state.screen == "analysis" and self.state.last_report:
            report = self.state.last_report
            table = Table(title="Language statistics", border_style=CYAN)
            table.add_column("Language")
            table.add_column("Files", justify="right")
            table.add_column("Percent", justify="right")
            for language in report.languages:
                table.add_row(
                    safe_terminal_text(language.language, 128),
                    str(language.file_count),
                    f"{language.percentage:.2f}%",
                )
            return Group(
                Text(
                    f"Workspace: {report.workspace_identifier}\n"
                    f"Files: {report.file_count}\nComplete: {report.complete}",
                    style=TEXT,
                ),
                table,
                Text(self.state.message, style=MUTED),
            )
        content = safe_terminal_text(self.state.message)
        if self.state.screen == "history":
            return self._history_content(content)
        if self.state.screen == "replay":
            return Text(
                content + "\n\nHistorical replay only. No capability will be executed.",
                style=TEXT,
            )
        if self.state.screen == "ai":
            return self._ai_content(content)
        return Text(content + "\n\nPress b or Esc to return home.", style=TEXT)

    def _history_content(self, message: str) -> object:
        table = Table(title="Recorded executions", border_style=CYAN)
        table.add_column("ID")
        table.add_column("Capability")
        table.add_column("Status")
        for index, record in enumerate(self.state.history_records):
            marker = "❯" if index == self.state.history_selected else " "
            table.add_row(
                marker + safe_terminal_text(record.execution_id, 12),
                safe_terminal_text(record.capability_identifier or "-", 30),
                safe_terminal_text(record.status, 16),
            )
        return Group(table, Text(message, style=MUTED))

    def _ai_content(self, message: str) -> object:
        models = (
            ", ".join(
                safe_terminal_text(model.identifier, 64)
                for model in self.state.ai_models
            )
            or "none"
        )
        selected = (
            self.state.ai_models[self.state.ai_selected].identifier
            if self.state.ai_models
            else "none"
        )
        response = (
            safe_terminal_text(self.state.ai_response, 4_000)
            if self.state.ai_response
            else "No response yet."
        )
        return Text(
            f"{message}\n\nModels: {models}\n"
            f"Selected: {safe_terminal_text(selected, 64)}\n"
            "Repeated single-turn prompts. Prior messages are not sent.\n"
            "Commands: /model /clear /back /help\n\nResponse:\n"
            f"{response}",
            style=TEXT,
        )

    def _render_narrow(self) -> None:
        self.console.clear()
        self.console.print(Text("ZEROAGENT X", style=f"bold {CYAN}"))
        self.console.print(
            Text(f"v{__version__} · {self.state.workspace.name}", style=MUTED)
        )
        for index, item in enumerate(MENU, start=1):
            marker = ">" if index - 1 == self.state.selected else " "
            self.console.print(
                f"{marker} {index}. {item}", style=PURPLE if marker == ">" else TEXT
            )
        self.console.print(self.state.message, style=MUTED)

    def handle(self, command: str) -> bool:
        """Handle one tested key/command input. Return False only to quit."""
        normalized = command.strip()
        if normalized in {"q", "/exit", "ctrl_c"}:
            return False
        if normalized in {"esc", "\x1b"}:
            self.state.screen = "home"
            return True
        if normalized in {"up", "k", "\x1b[A"}:
            if (
                self.state.screen in {"history", "replay"}
                and self.state.history_records
            ):
                self.state.history_selected = (self.state.history_selected - 1) % len(
                    self.state.history_records
                )
                return True
            self.state.selected = (self.state.selected - 1) % len(MENU)
            return True
        if normalized in {"down", "j", "\x1b[B"}:
            if (
                self.state.screen in {"history", "replay"}
                and self.state.history_records
            ):
                self.state.history_selected = (self.state.history_selected + 1) % len(
                    self.state.history_records
                )
                return True
            self.state.selected = (self.state.selected + 1) % len(MENU)
            return True
        if normalized == "b":
            self.state.screen = "home"
            return True
        if normalized.isdigit() and 1 <= int(normalized) <= len(MENU):
            self.state.selected = int(normalized) - 1
            return self.activate()
        if normalized in {"enter", ""}:
            if self.state.screen == "history":
                return self.inspect_history()
            if self.state.screen == "replay":
                return self.replay_history()
            return self.activate()
        if self.state.screen == "ai":
            return self.ai_ask(normalized)
        if normalized.startswith("/"):
            return self._slash(normalized)
        self.state.message = f"Invalid input: {normalized}. Use /help for commands."
        return True

    def _slash(self, command: str) -> bool:
        name, _, argument = command.partition(" ")
        if name == "/analyze" and argument:
            self.state.workspace = Path(argument).expanduser()
            return self.analyze()
        if name in {"/run", "/verify"} and argument:
            return self._run_task(argument, verify=name == "/verify")
        if self.state.screen == "ai" and name == "/back":
            self.state.screen = "home"
            return True
        if self.state.screen == "ai" and name == "/clear":
            self.state.ai_response = None
            self.state.message = "Response cleared."
            return True
        if self.state.screen == "ai" and name == "/model":
            return self.next_model()
        commands: dict[str, Callable[[], bool]] = {
            "/analyze": self.analyze,
            "/run": self.run,
            "/verify": self.verify,
            "/history": self.show_history,
            "/replay": self.show_replay,
            "/model": self.ai_status,
            "/settings": self.settings,
            "/help": self.help,
        }
        handler = commands.get(name)
        if handler is None:
            self.state.message = f"Unknown command: {command}"
            return True
        return handler()

    def activate(self) -> bool:
        return (
            self.analyze,
            self.run,
            self.verify,
            self.show_history,
            self.show_replay,
            self.ai_status,
            self.settings,
        )[self.state.selected]()

    def analyze(self) -> bool:
        try:
            self.state.last_report = analyze_repository(self.state.workspace)
            self.state.screen = "analysis"
            self.state.message = (
                "Repository analysis completed from actual workspace data."
            )
        except WorkspaceError as error:
            self.state.screen = "error"
            self.state.message = f"Analysis failed: {error}"
        return True

    def run(self) -> bool:
        return self._run_task("Analyze this repository", verify=False)

    def _run_task(self, task: str, *, verify: bool) -> bool:
        try:
            decision, result = run_task(task, self.state.workspace)
            self.state.last_report = (
                result if isinstance(result, AnalysisReport) else None
            )
            self.state.screen = "verify" if verify else "run"
            self.state.message = (
                f"Ran {decision.selected_capability}. Recording remains opt-in."
            )
            if verify:
                proof = verify_execution(decision, result, self.state.workspace)
                self.state.message = (
                    f"Proof status: {proof.overall_status}. "
                    f"{len(proof.checks)} checks ran."
                )
        except (RoutingError, WorkspaceError) as error:
            self.state.screen = "error"
            self.state.message = f"Run failed: {error}"
        return True

    def verify(self) -> bool:
        return self._run_task("Analyze this repository", verify=True)

    def show_history(self) -> bool:
        try:
            records = history(LocalStorage(), 10)
            self.state.screen = "history"
            self.state.history_records = records
            self.state.history_selected = 0
            self.state.message = (
                f"{len(records)} local record(s). Use CLI inspect/replay with an "
                "execution ID."
            )
        except StorageError as error:
            self.state.screen = "error"
            self.state.message = f"History failed: {error}"
        return True

    def show_replay(self) -> bool:
        self.show_history()
        self.state.screen = "replay"
        self.state.message = (
            "Select record with arrows and Enter to display historical events."
        )
        return True

    def inspect_history(self) -> bool:
        if not self.state.history_records:
            self.state.message = "No execution records to inspect."
            return True
        record = self.state.history_records[self.state.history_selected]
        self.state.message = (
            f"Execution {safe_terminal_text(record.execution_id, 32)}\n"
            + "\n".join(
                f"{event.sequence}. {safe_terminal_text(event.event_type, 64)}"
                for event in record.events
            )
        )
        return True

    def replay_history(self) -> bool:
        if not self.state.history_records:
            self.state.message = "No execution records to replay."
            return True
        record = replay(self.state.history_records[self.state.history_selected])
        self.state.message = (
            "Historical replay only. No capability will be executed.\n"
            + "\n".join(
                f"{event.sequence}. {safe_terminal_text(event.event_type, 64)}"
                for event in record.events
            )
        )
        return True

    def ai_status(self) -> bool:
        try:
            info = LocalAIService(load_settings()).doctor()
            self.state.screen = "ai"
            if not info.reachable:
                self.state.ai_models = []
                failure = safe_terminal_text(
                    info.error_message or "service unreachable", 160
                )
                self.state.message = (
                    f"Ollama unavailable at {safe_terminal_text(info.endpoint, 128)}: "
                    f"{failure}"
                )
                return True
            self.state.ai_models = LocalAIService(load_settings()).models()
            self.state.ai_selected = 0
            self.state.message = (
                "Local Ollama available. Select model, then type a prompt."
            )
        except ProviderError as error:
            self.state.screen = "ai"
            self.state.message = f"Local AI unavailable: {error}"
        return True

    def next_model(self) -> bool:
        if not self.state.ai_models:
            self.state.message = (
                "No installed models. Install one manually, then refresh Local AI "
                "screen."
            )
            return True
        self.state.ai_selected = (self.state.ai_selected + 1) % len(
            self.state.ai_models
        )
        selected_model = self.state.ai_models[self.state.ai_selected].identifier
        self.state.message = f"Selected model: {safe_terminal_text(selected_model, 64)}"
        return True

    def ai_ask(self, prompt: str) -> bool:
        if not self.state.ai_models:
            self.state.message = "Local AI unavailable or no installed model."
            return True
        try:
            model = self.state.ai_models[self.state.ai_selected].identifier
            response = LocalAIService(load_settings()).ask(prompt, model)
            self.state.ai_response = response.response
            self.state.message = (
                f"Received local response from {safe_terminal_text(model, 64)}."
            )
        except (ProviderError, ValueError) as error:
            self.state.message = (
                f"Local AI request failed: {safe_terminal_text(error, 160)}"
            )
        return True

    def settings(self) -> bool:
        settings = load_settings()
        self.state.screen = "settings"
        self.state.message = (
            f"Read-only: network={settings.network_enabled}, "
            f"telemetry={settings.telemetry_enabled}, "
            f"shell={settings.shell_command_execution_enabled}, "
            f"local_ai={settings.local_ai_enabled}."
        )
        return True

    def help(self) -> bool:
        self.state.screen = "help"
        self.state.message = (
            "Commands: /analyze /run /verify /history /replay /model /settings "
            "/help /exit"
        )
        return True

    def run_interactive(self) -> None:
        """Run terminal session only when stdin and stdout are interactive."""
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError(
                "TUI requires an interactive terminal; use standard CLI commands "
                "instead"
            )
        try:
            while True:
                self.render()
                raw = self._read_key()
                if raw == "/":
                    raw = self._read_command()
                if not self.handle(raw):
                    break
        except (EOFError, KeyboardInterrupt):
            self.console.print("\n[muted]ZEROAGENT X session closed.[/muted]")

    @contextmanager
    def _raw_terminal(self) -> Iterator[None]:
        if sys.platform == "win32":
            yield
            return
        import termios
        import tty

        descriptor = sys.stdin.fileno()
        saved = termios.tcgetattr(descriptor)
        try:
            tty.setraw(descriptor)
            yield
        finally:
            termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)

    def _read_key(self) -> str:
        with self._raw_terminal():
            if sys.platform == "win32":
                import msvcrt

                key = msvcrt.getwch()
                if key in {"\x00", "\xe0"}:
                    return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
                return {"\r": "enter", "\x03": "ctrl_c", "\x1b": "esc"}.get(key, key)
            key = sys.stdin.read(1)
            if key == "\x1b":
                sequence = sys.stdin.read(2)
                return {"[A": "up", "[B": "down"}.get(sequence, "esc")
            return {"\r": "enter", "\n": "enter", "\x03": "ctrl_c"}.get(key, key)

    def _read_command(self) -> str:
        self.console.print("\n[cyan]command[/cyan] > /", end="")
        try:
            return "/" + input()
        except EOFError:
            return "/exit"
