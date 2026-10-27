"""ZEROAGENT X Premium Neon Full-Screen TUI with Alternate-Screen Isolation."""

from __future__ import annotations

import re
import select
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from zeroagent import __version__
from zeroagent.ai.models import InstalledModel
from zeroagent.ai.service import LocalAIService
from zeroagent.blackbox.history import history
from zeroagent.blackbox.replay import replay
from zeroagent.blackbox.storage import LocalStorage
from zeroagent.config import load_settings
from zeroagent.context import (
    build_context,
    context_prompt,
    select_context,
)
from zeroagent.core.repository import AnalysisReport, analyze_repository
from zeroagent.editing import (
    PatchProposal,
    approve,
    load_proposal,
)
from zeroagent.editing import (
    apply as apply_patch,
)
from zeroagent.editing import (
    preview as preview_patch,
)
from zeroagent.planning import (
    create_plan,
    validate_plan,
)
from zeroagent.proof.engine import verify_execution
from zeroagent.security.workspace import WorkspaceError
from zeroagent.testing import (
    ALLOWLISTED_RUNNERS,
    TestEvidence,
    TestSpecification,
    approve_test,
    execute_test,
    make_test_spec,
)

# Midnight Neon Theme Palette
BG_MAIN = "#080D18"
BG_PANEL = "#111827"
BG_INPUT = "#182235"
CYAN = "#00E5FF"
PURPLE = "#A855F7"
GREEN = "#39FF88"
AMBER = "#FFCA65"
RED = "#FF5C7A"
TEXT = "#EAF2FF"
MUTED = "#8B9BB4"

CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

MENU = (
    ("Analyze Repository", "Inspect repository structure, files, and language stats"),
    ("Ask About Repository", "Discover context and query model with authorization"),
    ("Plan Agent Task", "Formulate deterministic task plan (planning only)"),
    ("Safe Code Editing", "Review unified diff and apply with exact approval"),
    ("Run Controlled Tests", "Execute allowlisted pytest suite under boundaries"),
    ("Verify Execution", "Run independent ProofEngine evidence verification"),
    ("Execution History", "Inspect local execution records and audit traces"),
    ("Historical Replay", "Display chronological events of past execution (read-only)"),
    ("Local AI Chat", "Conversational interface with installed local Ollama models"),
    ("Settings", "Inspect active local policies and system parameters"),
)


def safe_terminal_text(value: object, limit: int = 4_000) -> str:
    """Bound untrusted terminal text and remove control sequences."""
    return CONTROL_CHARACTERS.sub("?", str(value))[:limit]


@dataclass
class TuiState:
    workspace: Path = field(default_factory=Path.cwd)
    selected_index: int = 0
    current_screen: str = "home"
    scroll_offset: int = 0
    message: str = (
        "Ready. Navigate with ↑/↓, Enter to select, Esc to return, q to exit."
    )
    last_report: AnalysisReport | None = None
    context_selection: Any | None = None
    context_report: Any | None = None
    edit_proposal: PatchProposal | None = None
    edit_approved: bool = False
    test_spec: TestSpecification | None = None
    test_approved: bool = False
    history_records: list[Any] = field(default_factory=list)
    history_selected: int = 0
    ai_models: list[InstalledModel] = field(default_factory=list)
    ai_selected: int = 0
    ai_history: list[tuple[str, str]] = field(default_factory=list)
    input_buffer: str = ""


class NeonMinimalTui:
    """Full-screen alternate-screen menu-driven TUI with Midnight Neon styling."""

    def __init__(
        self, console: Console | None = None, workspace: Path | None = None
    ) -> None:
        self.console = console or Console()
        self.state = TuiState(workspace=workspace or Path.cwd())

    # -------------------------------------------------------------------------
    # Visual Branding: Geometric X Logo & Header
    # -------------------------------------------------------------------------
    def _render_logo(self, compact: bool = False) -> Text:
        """Render geometric futuristic X logo with Cyan on left and Purple on right."""
        logo = Text()
        if compact:
            logo.append("╭─────────╮\n", style=CYAN)
            logo.append("│ ", style=CYAN)
            logo.append("██╗", style=f"bold {CYAN}")
            logo.append(" ", style=TEXT)
            logo.append("██╗", style=f"bold {PURPLE}")
            logo.append(" │\n", style=PURPLE)
            logo.append("│ ", style=CYAN)
            logo.append("╚██", style=f"bold {CYAN}")
            logo.append("█╔╝", style=f"bold {PURPLE}")
            logo.append(" │\n", style=PURPLE)
            logo.append("│ ", style=CYAN)
            logo.append("██╔", style=f"bold {CYAN}")
            logo.append("██╗", style=f"bold {PURPLE}")
            logo.append(" │\n", style=PURPLE)
            logo.append("│ ", style=CYAN)
            logo.append("██║", style=f"bold {CYAN}")
            logo.append(" ", style=TEXT)
            logo.append("██║", style=f"bold {PURPLE}")
            logo.append(" │\n", style=PURPLE)
            logo.append("╰─────────╯", style=PURPLE)
            return logo

        logo.append("╭──────────╮\n", style=CYAN)
        logo.append("│ ", style=CYAN)
        logo.append("██╗", style=f"bold {CYAN}")
        logo.append("  ", style=TEXT)
        logo.append("██╗", style=f"bold {PURPLE}")
        logo.append(" │\n", style=PURPLE)
        logo.append("│ ", style=CYAN)
        logo.append("╚██╗", style=f"bold {CYAN}")
        logo.append("██╔╝", style=f"bold {PURPLE}")
        logo.append(" │\n", style=PURPLE)
        logo.append("│  ", style=CYAN)
        logo.append("╚███╔╝", style=f"bold {TEXT}")
        logo.append("  │\n", style=PURPLE)
        logo.append("│  ", style=CYAN)
        logo.append("██╔██╗", style=f"bold {TEXT}")
        logo.append("  │\n", style=PURPLE)
        logo.append("│ ", style=CYAN)
        logo.append("██╔╝", style=f"bold {CYAN}")
        logo.append("╚██╗", style=f"bold {PURPLE}")
        logo.append(" │\n", style=PURPLE)
        logo.append("│ ", style=CYAN)
        logo.append("██║", style=f"bold {CYAN}")
        logo.append("  ", style=TEXT)
        logo.append("██║", style=f"bold {PURPLE}")
        logo.append(" │\n", style=PURPLE)
        logo.append("╰──────────╯", style=PURPLE)
        return logo

    def _header(self, compact: bool = False) -> Panel:
        logo_text = self._render_logo(compact=compact)
        grid = Table.grid(padding=(0, 2))
        grid.add_column()
        grid.add_column()

        meta = Text()
        meta.append("ZEROAGENT X", style=f"bold {CYAN}")
        meta.append(f"  v{__version__}\n", style=MUTED)
        meta.append("LOCAL-FIRST · PROOF-DRIVEN\n", style=f"bold {PURPLE}")
        meta.append("Don't Just Run AI. Prove It Works.\n", style=TEXT)
        meta.append(
            f"Workspace: {safe_terminal_text(self.state.workspace)}\n", style=MUTED
        )
        meta.append(
            "● Router  ● ProofEngine  ● BlackBox  ○ Ollama: Local AI", style=GREEN
        )

        grid.add_row(logo_text, meta)
        return Panel(grid, style=f"on {BG_PANEL}", border_style=CYAN, padding=(0, 1))

    def _footer(self) -> Panel:
        bar = Table.grid(expand=True)
        bar.add_column(ratio=2)
        bar.add_column(ratio=1, justify="right")

        nav = Text()
        nav.append("↑/↓", style=f"bold {CYAN}")
        nav.append(" Navigate  ", style=MUTED)
        nav.append("Enter", style=f"bold {CYAN}")
        nav.append(" Select  ", style=MUTED)
        nav.append("Esc", style=f"bold {CYAN}")
        nav.append(" Back  ", style=MUTED)
        nav.append("q", style=f"bold {CYAN}")
        nav.append(" Exit  ", style=MUTED)
        nav.append("/", style=f"bold {CYAN}")
        nav.append(" Command", style=MUTED)

        brand = Text("◈ ZERO PAID API REQUIRED ◈", style=f"bold {PURPLE}")
        bar.add_row(nav, brand)
        return Panel(bar, style=f"on {BG_PANEL}", border_style=PURPLE, padding=(0, 1))

    # -------------------------------------------------------------------------
    # Screen Renderers
    # -------------------------------------------------------------------------
    def _render_home(self) -> object:
        layout = Table.grid(expand=True)
        layout.add_column(ratio=1)
        layout.add_column(ratio=2)

        # Left: Quick status
        status_panel = Text()
        status_panel.append("WORKSPACE TARGET\n", style=f"bold {CYAN}")
        status_panel.append(
            f"{safe_terminal_text(self.state.workspace)}\n\n", style=TEXT
        )
        status_panel.append("ENGINE CAPABILITIES\n", style=f"bold {CYAN}")
        status_panel.append("✔ Repository Intelligence (Read-only)\n", style=GREEN)
        status_panel.append("✔ ZeroCost Router (Deterministic)\n", style=GREEN)
        status_panel.append("✔ ProofEngine (Evidence-backed)\n", style=GREEN)
        status_panel.append("✔ AgentBlackBox (Audit traces)\n", style=GREEN)
        status_panel.append("✔ Context Engine (Bounded excerpts)\n", style=GREEN)
        status_panel.append("✔ Safe Code Editing (Approval bound)\n", style=GREEN)
        status_panel.append("✔ Controlled Testing (pytest allowlist)\n", style=GREEN)
        status_panel.append("○ Local Ollama (Optional loopback)\n\n", style=MUTED)
        status_panel.append("DESCRIPTION\n", style=f"bold {CYAN}")
        _, selected_desc = MENU[self.state.selected_index]
        status_panel.append(selected_desc, style=MUTED)

        # Right: Selectable 10-Item Menu
        menu_text = Text()
        menu_text.append("MAIN MENU\n", style=f"bold {CYAN}")
        for idx, (title, _) in enumerate(MENU, start=1):
            is_selected = idx - 1 == self.state.selected_index
            marker = "❯ " if is_selected else "  "
            style = f"bold {CYAN} on {BG_INPUT}" if is_selected else TEXT
            prefix = f"{idx:02d}. "
            menu_text.append(f"{marker}{prefix}{title}\n", style=style)

        layout.add_row(
            Panel(
                status_panel,
                title="[cyan]Status[/cyan]",
                border_style=MUTED,
                style=f"on {BG_PANEL}",
            ),
            Panel(
                menu_text,
                title="[purple]Select Action[/purple]",
                border_style=PURPLE,
                style=f"on {BG_PANEL}",
            ),
        )
        return layout

    def _render_analyze(self) -> object:
        if not self.state.last_report:
            return Text(
                "Press Enter to execute repository analysis.\n\nEsc to return.",
                style=TEXT,
            )
        rep = self.state.last_report
        table = Table(
            title=f"Language Breakdown for '{rep.workspace_identifier}'",
            border_style=CYAN,
        )
        table.add_column("Language")
        table.add_column("Files", justify="right")
        table.add_column("Percentage", justify="right")
        for item in rep.languages:
            table.add_row(
                safe_terminal_text(item.language, 64),
                str(item.file_count),
                f"{item.percentage:.1f}%",
            )
        meta = Text()
        meta.append(
            f"Files: {rep.file_count} | Directories: {rep.directory_count}\n",
            style=TEXT,
        )
        meta.append(
            f"Manifests: {', '.join(rep.manifests) if rep.manifests else 'None'}\n",
            style=MUTED,
        )
        meta.append(
            f"Completeness: {'Complete' if rep.complete else 'Partial'}\n",
            style=GREEN if rep.complete else AMBER,
        )
        return Group(
            meta,
            table,
            Text("\nPress Enter to re-analyze. Esc to return.", style=MUTED),
        )

    def _render_context(self) -> object:
        text = Text()
        text.append("ASK ABOUT REPOSITORY (CONTEXT ENGINE)\n", style=f"bold {CYAN}")
        text.append(
            "Discovers relevant source files and builds bounded context safely.\n\n",
            style=MUTED,
        )
        if self.state.context_selection:
            sel = self.state.context_selection
            text.append(f"Query: {sel.question}\n", style=f"bold {TEXT}")
            text.append(f"Candidates Found: {len(sel.selections)}\n", style=TEXT)
            for s in sel.selections[:8]:
                text.append(f"  • {s.path} (score: {s.score})\n", style=MUTED)
            text.append(
                "\nTo send excerpts to Ollama, execute /allow-context <question>.\n",
                style=AMBER,
            )
        else:
            text.append(
                "Use /context <question> to select relevant candidate sources.\n",
                style=TEXT,
            )
        if self.state.context_report:
            text.append(
                f"\nLast response: {safe_terminal_text(self.state.message)}\n",
                style=TEXT,
            )
        text.append("\nEsc to return to Home.", style=MUTED)
        return text

    def _render_plan(self) -> object:
        text = Text()
        text.append("PLAN AGENT TASK (PLANNING ENGINE)\n", style=f"bold {CYAN}")
        text.append(
            "Deterministic task planner & tool registry (planning only).\n\n",
            style=MUTED,
        )
        text.append(
            "Use /plan <task description> to formulate a task execution plan.\n",
            style=TEXT,
        )
        text.append(f"\n{self.state.message}\n", style=TEXT)
        text.append("\nEsc to return to Home.", style=MUTED)
        return text

    def _render_edit(self) -> object:
        text = Text()
        text.append("SAFE CODE EDITING\n", style=f"bold {CYAN}")
        text.append(
            "Controlled patch validation, diff preview, and exact approval.\n\n",
            style=MUTED,
        )
        if self.state.edit_proposal:
            prop = self.state.edit_proposal
            text.append(f"Loaded Proposal ID: {prop.proposal_id}\n", style=TEXT)
            text.append(f"Canonical Digest: {prop.digest}\n", style=f"bold {CYAN}")
            text.append(f"Changes: {len(prop.changes)} file(s)\n", style=TEXT)
            text.append(f"Explanation: {prop.explanation}\n", style=MUTED)
            appr_status = "APPROVED" if self.state.edit_approved else "PENDING APPROVAL"
            text.append(
                f"Approval Status: {appr_status}\n\n",
                style=GREEN if self.state.edit_approved else AMBER,
            )
            text.append(
                "Commands: /edit-preview | /edit-approve <digest> | /edit-apply\n",
                style=CYAN,
            )
        else:
            text.append(
                "No patch proposal loaded.\nUse /edit-load <file> to inspect.\n",
                style=TEXT,
            )
        text.append(f"\nStatus: {self.state.message}\n", style=MUTED)
        text.append("\nEsc to return to Home.", style=MUTED)
        return text

    def _render_test(self) -> object:
        text = Text()
        text.append("RUN CONTROLLED TESTS\n", style=f"bold {CYAN}")
        text.append(
            "Allowlisted test execution (pytest) with process boundaries.\n\n",
            style=MUTED,
        )
        if self.state.test_spec:
            spec = self.state.test_spec
            text.append(f"Specification ID: {spec.specification_id}\n", style=TEXT)
            text.append(
                f"Runner: {spec.runner} ({sys.executable} -m {spec.runner})\n",
                style=TEXT,
            )
            text.append(f"Arguments: {spec.arguments}\n", style=TEXT)
            text.append(f"Timeout: {spec.timeout_seconds}s\n", style=TEXT)
            text.append(f"Canonical Digest: {spec.digest}\n", style=f"bold {CYAN}")
            test_appr = "APPROVED" if self.state.test_approved else "PENDING APPROVAL"
            text.append(
                f"Approval: {test_appr}\n\n",
                style=GREEN if self.state.test_approved else AMBER,
            )
            text.append(
                "Commands: /test-preview | /test-approve <digest> | /test-run\n",
                style=CYAN,
            )
        else:
            text.append(
                "No test specification created.\nUse /test-spec to create one.\n",
                style=TEXT,
            )
        text.append(f"\nStatus: {self.state.message}\n", style=MUTED)
        text.append("\nEsc to return to Home.", style=MUTED)
        return text

    def _render_verify(self) -> object:
        text = Text()
        text.append("VERIFY EXECUTION (PROOFENGINE)\n", style=f"bold {CYAN}")
        text.append(
            "Independent structural evidence checks for operations.\n\n",
            style=MUTED,
        )
        text.append(
            "Use Enter or /verify to execute verified repository analysis.\n",
            style=TEXT,
        )
        text.append(f"\n{self.state.message}\n", style=TEXT)
        text.append("\nEsc to return to Home.", style=MUTED)
        return text

    def _render_history(self) -> object:
        text = Text()
        text.append("EXECUTION HISTORY (AGENTBLACKBOX)\n", style=f"bold {CYAN}")
        text.append(
            "Local audit records and lifecycle events. Never records raw source.\n\n",
            style=MUTED,
        )
        if not self.state.history_records:
            try:
                self.state.history_records = history(LocalStorage(), limit=10)
            except Exception:
                self.state.history_records = []
        if self.state.history_records:
            table = Table(title="Recent Execution Records", border_style=CYAN)
            table.add_column("ID")
            table.add_column("Capability")
            table.add_column("Status")
            table.add_column("Started")
            for idx, r in enumerate(self.state.history_records):
                marker = "❯ " if idx == self.state.history_selected else "  "
                table.add_row(
                    marker + safe_terminal_text(r.execution_id[:12], 12),
                    safe_terminal_text(r.capability_identifier or "-", 30),
                    safe_terminal_text(r.status, 16),
                    safe_terminal_text(str(r.started_at)[:19], 20),
                )
            return Group(
                text,
                table,
                Text("\nEnter to inspect selected record. Esc to return.", style=MUTED),
            )
        text.append("No execution records found in BlackBox storage.\n", style=MUTED)
        text.append("\nEsc to return to Home.", style=MUTED)
        return text

    def _render_replay(self) -> object:
        text = Text()
        text.append("HISTORICAL REPLAY\n", style=f"bold {CYAN}")
        text.append(
            "Notice: Historical replay only. No capability or tools are executed.\n\n",
            style=f"bold {AMBER}",
        )
        text.append(f"{self.state.message}\n", style=TEXT)
        text.append("\nEsc to return to Home.", style=MUTED)
        return text

    def _render_ai(self) -> object:
        text = Text()
        text.append("LOCAL AI CHAT (OLLAMA)\n", style=f"bold {CYAN}")
        text.append(
            "Loopback only (127.0.0.1:11434). Zero cloud or paid API access.\n",
            style=MUTED,
        )
        if self.state.ai_models:
            sel_model = self.state.ai_models[self.state.ai_selected].identifier
            text.append(
                f"Active Model: {sel_model} (/model to switch)\n\n", style=GREEN
            )
        else:
            text.append(
                "Ollama status: Checking or unavailable. Use /model to refresh.\n\n",
                style=AMBER,
            )

        for role, msg in self.state.ai_history[-6:]:
            prefix = "User" if role == "user" else "Ollama"
            color = CYAN if role == "user" else PURPLE
            text.append(f"{prefix}: ", style=f"bold {color}")
            text.append(f"{msg}\n\n", style=TEXT)

        text.append(
            "Type a prompt or command (/clear, /model, /back). Esc to return.",
            style=MUTED,
        )
        return text

    def _render_settings(self) -> object:
        cfg = load_settings()
        table = Table(title="System & Security Parameters", border_style=CYAN)
        table.add_column("Setting")
        table.add_column("Value")
        table.add_row("Version", __version__)
        table.add_row("Workspace", safe_terminal_text(self.state.workspace, 80))
        table.add_row(
            "Telemetry", "DISABLED" if not cfg.telemetry_enabled else "ENABLED"
        )
        table.add_row(
            "Network Access", "DISABLED" if not cfg.network_enabled else "ENABLED"
        )
        table.add_row(
            "Cloud Providers",
            "DISABLED" if not cfg.cloud_providers_enabled else "ENABLED",
        )
        table.add_row(
            "Shell Execution",
            "DISABLED" if not cfg.shell_command_execution_enabled else "ENABLED",
        )
        table.add_row("Local AI Endpoint", safe_terminal_text(cfg.ollama_endpoint, 40))
        table.add_row(
            "Retention",
            f"{cfg.blackbox_max_records} records, {cfg.blackbox_max_record_bytes} B",
        )
        return Group(
            table,
            Text(
                "\nAll parameters enforce local execution.\nEsc to return to Home.",
                style=MUTED,
            ),
        )

    # -------------------------------------------------------------------------
    # Screen Assembly
    # -------------------------------------------------------------------------
    def _render_screen_body(self) -> Panel:
        s = self.state.current_screen
        if s == "home":
            content = self._render_home()
            title = "[bold purple]HOME · MAIN MENU[/bold purple]"
        elif s == "analyze":
            content = self._render_analyze()
            title = "[bold cyan]ANALYZE REPOSITORY[/bold cyan]"
        elif s == "context":
            content = self._render_context()
            title = "[bold cyan]ASK ABOUT REPOSITORY[/bold cyan]"
        elif s == "plan":
            content = self._render_plan()
            title = "[bold cyan]PLAN AGENT TASK[/bold cyan]"
        elif s == "edit":
            content = self._render_edit()
            title = "[bold cyan]SAFE CODE EDITING[/bold cyan]"
        elif s == "test":
            content = self._render_test()
            title = "[bold cyan]RUN CONTROLLED TESTS[/bold cyan]"
        elif s == "verify":
            content = self._render_verify()
            title = "[bold cyan]VERIFY EXECUTION[/bold cyan]"
        elif s == "history":
            content = self._render_history()
            title = "[bold cyan]EXECUTION HISTORY[/bold cyan]"
        elif s == "replay":
            content = self._render_replay()
            title = "[bold cyan]HISTORICAL REPLAY[/bold cyan]"
        elif s == "ai":
            content = self._render_ai()
            title = "[bold purple]LOCAL AI CHAT[/bold purple]"
        elif s == "settings":
            content = self._render_settings()
            title = "[bold cyan]SETTINGS[/bold cyan]"
        else:
            content = Text(
                f"Unknown screen '{s}'. Press Esc to return home.", style=TEXT
            )
            title = "[bold red]ERROR[/bold red]"

        return Panel(
            content,
            title=title,
            border_style=PURPLE,
            style=f"on {BG_PANEL}",
            padding=(1, 2),
        )

    def render(self) -> None:
        """Render complete alternate screen frame."""
        width = self.console.size.width
        compact = width < 85
        frame = Table.grid(expand=True)
        frame.add_row(self._header(compact=compact))
        frame.add_row(self._render_screen_body())
        frame.add_row(self._footer())

        # Print cleanly filling the alternate buffer
        self.console.clear()
        self.console.print(frame)

    # -------------------------------------------------------------------------
    # Navigation & Interaction
    # -------------------------------------------------------------------------
    def handle(self, raw_input: str) -> bool:
        cmd = raw_input.strip()
        if not cmd:
            if self.state.current_screen == "home":
                return self._select_current_menu()
            return True

        if cmd in {"q", "exit", "/exit", "ctrl_c"}:
            return False

        if cmd in {"esc", "\x1b"}:
            self.state.current_screen = "home"
            self.state.message = "Returned to Main Menu."
            return True

        # Home screen numeric and arrow navigation
        if self.state.current_screen == "home":
            if cmd in {"up", "k", "\x1b[A"}:
                self.state.selected_index = (self.state.selected_index - 1) % len(MENU)
                return True
            if cmd in {"down", "j", "\x1b[B"}:
                self.state.selected_index = (self.state.selected_index + 1) % len(MENU)
                return True
            if cmd.isdigit() and 1 <= int(cmd) <= len(MENU):
                self.state.selected_index = int(cmd) - 1
                return self._select_current_menu()
            if cmd in {"enter", ""}:
                return self._select_current_menu()

        # History navigation
        if self.state.current_screen == "history":
            if cmd in {"up", "k", "\x1b[A"} and self.state.history_records:
                self.state.history_selected = (self.state.history_selected - 1) % len(
                    self.state.history_records
                )
                return True
            if cmd in {"down", "j", "\x1b[B"} and self.state.history_records:
                self.state.history_selected = (self.state.history_selected + 1) % len(
                    self.state.history_records
                )
                return True
            if cmd in {"enter", ""} and self.state.history_records:
                rec = self.state.history_records[self.state.history_selected]
                r_id = rec.execution_id[:12]
                self.state.message = (
                    f"Record {r_id}..:\nStatus: {rec.status}\nEvents: {len(rec.events)}"
                )
                return True

        # Slash commands
        if cmd.startswith("/"):
            return self._handle_slash(cmd)

        # AI Chat free text
        if self.state.current_screen == "ai":
            return self._handle_ai_prompt(cmd)

        self.state.message = (
            f"Unrecognized input '{cmd}'. Press Esc for Home or type /help."
        )
        return True

    def _select_current_menu(self) -> bool:
        idx = self.state.selected_index
        screens = [
            "analyze",
            "context",
            "plan",
            "edit",
            "test",
            "verify",
            "history",
            "replay",
            "ai",
            "settings",
        ]
        self.state.current_screen = screens[idx]
        if self.state.current_screen == "analyze" and not self.state.last_report:
            self._do_analyze()
        elif self.state.current_screen == "ai":
            self._query_ai_models()
        return True

    def _handle_slash(self, cmd: str) -> bool:
        name, _, argument = cmd.partition(" ")
        name = name.lower()

        if name == "/help":
            self.state.message = (
                "COMMANDS: /analyze | /context <q> | /plan <task> | /edit-load <f> | "
                "/edit-preview | /edit-approve <d> | /edit-apply | /test-spec | "
                "/test-preview | /test-approve <d> | /test-run | /exit"
            )
            return True
        if name == "/analyze":
            self.state.current_screen = "analyze"
            self._do_analyze()
            return True
        if name == "/context":
            self.state.current_screen = "context"
            self._do_context(argument or "Explain repository architecture")
            return True
        if name == "/allow-context":
            self.state.current_screen = "context"
            self._do_context_ask(argument or "Explain repository architecture")
            return True
        if name == "/plan":
            self.state.current_screen = "plan"
            self._do_plan(argument or "Analyze repository and improve error handling")
            return True
        if name == "/edit-load":
            self.state.current_screen = "edit"
            self._do_edit_load(argument)
            return True
        if name == "/edit-preview":
            self.state.current_screen = "edit"
            self._do_edit_preview()
            return True
        if name == "/edit-approve":
            self.state.current_screen = "edit"
            self._do_edit_approve(argument)
            return True
        if name == "/edit-apply":
            self.state.current_screen = "edit"
            self._do_edit_apply()
            return True
        if name == "/test-spec":
            self.state.current_screen = "test"
            self._do_test_spec(argument)
            return True
        if name == "/test-preview":
            self.state.current_screen = "test"
            self._do_test_preview()
            return True
        if name == "/test-approve":
            self.state.current_screen = "test"
            self._do_test_approve(argument)
            return True
        if name == "/test-run":
            self.state.current_screen = "test"
            self._do_test_run()
            return True
        if name == "/verify":
            self.state.current_screen = "verify"
            self._do_verify()
            return True
        if name == "/history":
            self.state.current_screen = "history"
            self.state.history_records = history(LocalStorage(), limit=10)
            return True
        if name == "/replay":
            self.state.current_screen = "replay"
            self._do_replay(argument)
            return True
        if name == "/model":
            self.state.current_screen = "ai"
            self._query_ai_models()
            if self.state.ai_models:
                self.state.ai_selected = (self.state.ai_selected + 1) % len(
                    self.state.ai_models
                )
            return True
        if name == "/clear":
            if self.state.current_screen == "ai":
                self.state.ai_history = []
            self.state.message = "Cleared."
            return True
        if name in {"/back", "/home"}:
            self.state.current_screen = "home"
            return True

        self.state.message = f"Unknown command '{name}'. Use /help."
        return True

    # -------------------------------------------------------------------------
    # Service Integrations (Safe & Verified)
    # -------------------------------------------------------------------------
    def _do_analyze(self) -> None:
        try:
            self.state.last_report = analyze_repository(self.state.workspace)
            self.state.message = (
                f"Analysis complete: {self.state.last_report.file_count} files found."
            )
        except WorkspaceError as err:
            self.state.message = f"Analysis failed: {err}"

    def _do_context(self, question: str) -> None:
        try:
            self.state.context_selection = select_context(
                self.state.workspace, question
            )
            self.state.message = (
                f"Selected {len(self.state.context_selection.selections)} candidates."
            )
        except Exception as err:
            self.state.message = f"Context selection error: {err}"

    def _do_context_ask(self, question: str) -> None:
        if not self.state.ai_models:
            self._query_ai_models()
        if not self.state.ai_models:
            self.state.message = (
                "Local AI unavailable: Ollama is not reachable at 127.0.0.1:11434."
            )
            return
        try:
            report = build_context(self.state.workspace, question, allow_context=True)
            self.state.context_report = report
            model = self.state.ai_models[self.state.ai_selected].identifier
            resp = LocalAIService(load_settings()).ask(context_prompt(report), model)
            self.state.message = f"Response from {model}:\n{resp.response[:500]}"
        except Exception as err:
            self.state.message = f"Context transfer error: {err}"

    def _do_plan(self, task: str) -> None:
        try:
            plan = validate_plan(create_plan(task, self.state.workspace))
            steps_desc = "\n".join(
                f"  • {s.identifier}: {s.description} [{s.tool}]" for s in plan.steps
            )
            self.state.message = f"Plan Status: {plan.status}\n{steps_desc}"
        except Exception as err:
            self.state.message = f"Plan generation failed: {err}"

    def _do_edit_load(self, path_str: str) -> None:
        p = Path(path_str.strip())
        try:
            self.state.edit_proposal = load_proposal(p)
            self.state.edit_approved = False
            d16 = self.state.edit_proposal.digest[:16]
            self.state.message = f"Proposal loaded: {d16}... Run /edit-preview."
        except Exception as err:
            self.state.message = f"Failed loading proposal: {err}"

    def _do_edit_preview(self) -> None:
        if not self.state.edit_proposal:
            self.state.message = "No proposal loaded. Use /edit-load <file>."
            return
        try:
            diff = preview_patch(self.state.edit_proposal, self.state.workspace)
            self.state.message = f"Diff Preview:\n{diff}"
        except Exception as err:
            self.state.message = f"Preview failed: {err}"

    def _do_edit_approve(self, digest: str) -> None:
        digest = digest.strip()
        if not self.state.edit_proposal:
            self.state.message = "No proposal loaded."
            return
        if digest != self.state.edit_proposal.digest:
            self.state.message = "Digest mismatch. Approval rejected."
            return
        self.state.edit_approved = True
        self.state.message = (
            f"Proposal {digest[:16]}... APPROVED. Use /edit-apply to execute."
        )

    def _do_edit_apply(self) -> None:
        if not self.state.edit_proposal or not self.state.edit_approved:
            self.state.message = (
                "Application blocked: explicit exact-digest approval required."
            )
            return
        recovery_dir = (
            Path.home()
            / ".zeroagent"
            / "recovery"
            / self.state.edit_proposal.proposal_id
        )
        try:
            appr = approve(self.state.edit_proposal, self.state.workspace)
            res = apply_patch(
                self.state.edit_proposal, appr, self.state.workspace, recovery_dir
            )
            self.state.edit_approved = False
            applied_str = ", ".join(res.applied_paths)
            self.state.message = (
                f"Patch Applied: {applied_str}. Recovery: {res.recovery_path}"
            )
        except Exception as err:
            self.state.message = f"Patch apply failed: {err}"

    def _do_test_spec(self, args_str: str) -> None:
        args = [a for a in args_str.split(" ") if a]
        try:
            self.state.test_spec = make_test_spec(
                self.state.workspace, runner="pytest", arguments=args
            )
            self.state.test_approved = False
            d16 = self.state.test_spec.digest[:16]
            self.state.message = f"Test Spec Created: {d16}... Run /test-preview."
        except Exception as err:
            self.state.message = f"Test spec creation failed: {err}"

    def _do_test_preview(self) -> None:
        if not self.state.test_spec:
            self.state.message = "No test specification exists. Use /test-spec."
            return
        cmd = f"{sys.executable} -m pytest {' '.join(self.state.test_spec.arguments)}"
        digest = self.state.test_spec.digest
        self.state.message = f"Test Preview:\nCommand: {cmd}\nDigest: {digest}"

    def _do_test_approve(self, digest: str) -> None:
        digest = digest.strip()
        if not self.state.test_spec:
            self.state.message = "No test spec exists."
            return
        if digest != self.state.test_spec.digest:
            self.state.message = "Digest mismatch. Test approval rejected."
            return
        self.state.test_approved = True
        self.state.message = f"Test Spec {digest[:16]}... APPROVED. Run with /test-run."

    def _do_test_run(self) -> None:
        if not self.state.test_spec or not self.state.test_approved:
            self.state.message = "Test execution blocked: exact approval required."
            return
        try:
            approval = approve_test(self.state.test_spec, self.state.workspace)
            res = execute_test(self.state.test_spec, approval, self.state.workspace)
            self.state.test_approved = False
            evidence = TestEvidence(
                specification_digest=self.state.test_spec.digest,
                approval_bound=True,
                runner_allowlisted=self.state.test_spec.runner in ALLOWLISTED_RUNNERS,
                execution_completed=res.status in ("PASSED", "FAILED"),
                exit_code_zero=res.exit_code == 0,
                output_integrity=not res.output_truncated,
            )
            proof = verify_execution(None, evidence, self.state.workspace)
            st = f"{res.status} (exit {res.exit_code})"
            self.state.message = f"Test Result: {st} | Proof: {proof.overall_status}"
        except Exception as err:
            self.state.message = f"Test execution error: {err}"

    def _do_verify(self) -> None:
        if not self.state.last_report:
            self._do_analyze()
        if self.state.last_report:
            proof = verify_execution(None, self.state.last_report, self.state.workspace)
            checks_num = len(proof.checks)
            st = f"{proof.overall_status} ({checks_num} checks)"
            self.state.message = f"Proof Verification Status: {st}"

    def _do_replay(self, record_id: str) -> None:
        if not record_id.strip():
            self.state.message = (
                "Historical replay requires an execution ID: /replay <id>"
            )
            return
        try:
            storage = LocalStorage()
            record = storage.load(record_id.strip())
            replayed = replay(record)
            events = "\n".join(
                f"  • {e.sequence}. {e.event_type} at {e.timestamp.isoformat()}"
                for e in replayed.events
            )
            self.state.message = (
                f"Replayed Execution {replayed.execution_id}:\n{events}"
            )
        except Exception as err:
            self.state.message = f"Replay failed: {err}"

    def _query_ai_models(self) -> None:
        try:
            service = LocalAIService(load_settings())
            info = service.doctor()
            if not info.reachable:
                self.state.ai_models = []
                self.state.message = f"Ollama service unreachable at {info.endpoint}."
                return
            self.state.ai_models = service.models()
            self.state.message = (
                f"Ollama online. {len(self.state.ai_models)} model(s) available."
            )
        except Exception as err:
            self.state.ai_models = []
            self.state.message = f"Model query error: {err}"

    def _handle_ai_prompt(self, prompt: str) -> bool:
        if not self.state.ai_models:
            self._query_ai_models()
        if not self.state.ai_models:
            self.state.message = (
                "Local AI unavailable: start Ollama locally at 127.0.0.1:11434."
            )
            return True
        model = self.state.ai_models[self.state.ai_selected].identifier
        self.state.ai_history.append(("user", prompt))
        try:
            service = LocalAIService(load_settings())
            resp = service.ask(prompt, model)
            self.state.ai_history.append(("agent", resp.response))
            self.state.message = f"Response received from local model '{model}'."
        except Exception as err:
            self.state.ai_history.append(("agent", f"Generation error: {err}"))
            self.state.message = f"Generation error: {err}"
        return True

    # -------------------------------------------------------------------------
    # Lifecycle & Terminal Raw / Alternate Screen Management
    # -------------------------------------------------------------------------
    @contextmanager
    def _raw_terminal(self) -> Iterator[None]:
        if sys.platform == "win32":
            yield
            return
        import termios
        import tty

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)

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
                # Non-blocking check for multi-byte escape sequences
                r, _, _ = select.select([sys.stdin], [], [], 0.05)
                if r:
                    seq = sys.stdin.read(2)
                    return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(
                        seq, "esc"
                    )
                return "esc"
            return {"\r": "enter", "\n": "enter", "\x03": "ctrl_c"}.get(key, key)

    def _read_line_input(self) -> str:
        self.console.print("\n[cyan]command[/cyan] > /", end="")
        try:
            return "/" + input()
        except EOFError:
            return "/exit"

    def run_interactive(self) -> None:
        """Run true full-screen terminal application in alternate screen buffer."""
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise RuntimeError("Interactive terminal required for ZEROAGENT X TUI.")

        # Enter terminal's alternate screen buffer via Rich console screen context
        with self.console.screen(hide_cursor=True):
            try:
                while True:
                    self.render()
                    key = self._read_key()
                    if key == "/":
                        cmd = self._read_line_input()
                        if not self.handle(cmd):
                            break
                    else:
                        if not self.handle(key):
                            break
            except (EOFError, KeyboardInterrupt):
                pass
            finally:
                self.console.clear()
