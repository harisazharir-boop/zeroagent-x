"""Graphite Textual interface for ZEROAGENT X."""

from __future__ import annotations

import asyncio
import os
import re
import textwrap
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from rich.highlighter import Highlighter
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from zeroagent import __version__
from zeroagent.ai.service import LocalAIService
from zeroagent.blackbox.history import history
from zeroagent.blackbox.replay import replay
from zeroagent.blackbox.storage import LocalStorage
from zeroagent.config import load_settings
from zeroagent.context import build_context, context_prompt, select_context
from zeroagent.core.repository import analyze_repository
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
from zeroagent.pipeline import PipelineEngine, PipelineError, PipelineState
from zeroagent.planning import TaskPlan, create_plan, validate_plan
from zeroagent.proof.engine import verify_execution
from zeroagent.routing.router import RoutingDecision, route_task, run_task
from zeroagent.testing import (
    ALLOWLISTED_RUNNERS,
    TestEvidence,
    approve_test,
    execute_test,
    make_test_spec,
)

MENU_ITEMS = (
    (
        "Agent Workspace",
        "Route supported local tasks, explicitly run them, then verify evidence.",
        "EXPLICIT RUN",
        "agent",
        "Agent Workspace",
    ),
    (
        "Analyze Repository",
        "Inspect repository structure, language breakdown, and bounded file metadata.",
        "READ ONLY",
        "analyze",
        "Repository Intelligence",
    ),
    (
        "Ask About Repository",
        "Preview context; transfer source files only with explicit authorization.",
        "LOCAL AI",
        "context",
        "Repository Research",
    ),
    (
        "Safe Code Editing",
        "Review changes, unified diffs, exact digest approval & atomic rollback.",
        "APPROVAL REQUIRED",
        "edit",
        "Patch Review Studio",
    ),
    (
        "Run Controlled Tests",
        "Execute allowlisted pytest suite under strict boundaries and exact approval.",
        "APPROVAL REQUIRED",
        "test",
        "Controlled Test Runner",
    ),
    (
        "Verify Execution",
        "Run independent ProofEngine structural evidence verification.",
        "EVIDENCE",
        "verify",
        "ProofEngine Dashboard",
    ),
    (
        "Execution History",
        "Browse sanitized AgentBlackBox execution audit records without secrets.",
        "BLACKBOX",
        "history",
        "Execution History",
    ),
    (
        "Historical Replay",
        "Inspect chronological events of past executions in read-only mode.",
        "READ ONLY",
        "replay",
        "Historical Event Replay",
    ),
    (
        "Local AI Chat",
        "Dedicated conversational interface with installed offline Ollama models.",
        "OFFLINE ONLY",
        "ai",
        "Local AI Conversation Studio",
    ),
    (
        "Settings",
        "Inspect active local-first policies, security boundaries, and diagnostics.",
        "LOCAL-FIRST",
        "settings",
        "Configuration Center",
    ),
)


class SignatureBrandHeader(Static):
    """Compact text-only product header."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="header-bar"):
            yield Static(
                "[bold #89B4FA]ZEROAGENT X[/bold #89B4FA]",
                id="header-wordmark",
            )
            yield Static(f"[#9CA3AF]v{__version__}[/#9CA3AF]", id="header-version")


PANEL_STYLES = {
    "information": "#343A45",
    "result": "#89B4FA",
    "evidence": "#89B4FA",
    "approval": "#E5C07B",
    "warning": "#E5C07B",
    "error": "#E06C75",
    "diff": "#89B4FA",
    "test": "#89B4FA",
    "history": "#89B4FA",
}


class OutputPanel(Static):
    """Output display supporting plain text and rich panels when required."""

    def __init__(self, content: str = "", *args, **kwargs) -> None:
        super().__init__(
            f"[#9CA3AF]{content}[/#9CA3AF]" if content else "",
            *args,
            **kwargs,
        )
        self.content_text = content

    def show(
        self,
        content: str | Syntax,
        title: str = "",
        kind: str = "result",
    ) -> None:
        self.content_text = (
            content
            if isinstance(content, str)
            else getattr(content, "code", str(content))
        )
        panel_kinds = {
            "error",
            "warning",
            "evidence",
            "diff",
            "approval",
            "test",
            "history",
        }
        if kind in panel_kinds:
            color = PANEL_STYLES.get(kind, "#89B4FA")
            panel = Panel(
                content,
                title=f"[{color}]{title}[/{color}]" if title else None,
                title_align="left",
                border_style=color,
                padding=(0, 1),
            )
            self.update(panel)
        else:
            self.update(content)
        self.set_class(True, kind)


class WorkflowStepper(Static):
    """Reusable visual workflow progress stepper with highlighted active steps."""

    def __init__(self, steps: list[str], current_index: int = 0) -> None:
        super().__init__()
        self.steps = steps
        self.current_index = current_index

    def compose(self) -> ComposeResult:
        parts: list[str] = []
        for idx, name in enumerate(self.steps):
            num = idx + 1
            if idx == self.current_index:
                parts.append(f"[bold #89B4FA]({num}) {name}[/bold #89B4FA]")
            elif idx < self.current_index:
                parts.append(f"[bold #39FF88]✓ {name}[/bold #39FF88]")
            else:
                parts.append(f"[dim #9CA3AF]{num} {name}[/dim #9CA3AF]")
        yield Static(" → ".join(parts), classes="workflow-stepper-text")


class ContextualFooter(Static):
    """Clean contextual footer with minimalist key hints, no redundant numbers."""

    def __init__(self, hints: str = "") -> None:
        super().__init__()
        self.hints = hints or (
            "[bold #89B4FA]↑↓[/bold #89B4FA] Navigate   "
            "[bold #89B4FA]Enter[/bold #89B4FA] Open Feature   "
            "[bold #89B4FA]/[/bold #89B4FA] Commands   "
            "[bold #9CA3AF]Esc[/bold #9CA3AF] Back   "
            "[bold #9CA3AF]q[/bold #9CA3AF] Exit"
        )

    def compose(self) -> ComposeResult:
        yield Static(self.hints, id="footer-text")

    def update_text(self, text: str) -> None:
        self.hints = text
        self.query_one("#footer-text", Static).update(text)


class SectionRule(Static):
    """Single full-width rule used by all workbench sections."""

    def __init__(self, id: str | None = None, classes: str | None = None) -> None:
        super().__init__("─" * 1000, id=id, classes=classes)


class TodoList(Static):
    """Read-only plan rows rendered as a hanging-indent todo list."""

    def set_items(self, items: list[tuple[str, str]]) -> None:
        longest_id = min(
            10, max((len(identifier) for identifier, _ in items), default=1)
        )
        table = Table.grid(expand=True, padding=(0, 1))
        table.add_column(width=3, no_wrap=True)
        table.add_column(width=longest_id, no_wrap=True)
        table.add_column(ratio=1, overflow="fold")
        for identifier, description in items:
            table.add_row(
                Text("[ ]", style="#89B4FA"),
                Text(identifier[:10], style="#6B7280"),
                Text(_bound_text(description, 400), style="#E5E7EB"),
            )
        self.items = items
        self.update(table)


class PlanResultView(Static):
    """Scrollable, non-executing plan result with fully visible todo rows."""

    ROWS = ("goal", "source", "steps", "requested", "safety", "next")

    def compose(self) -> ComposeResult:
        yield Static(
            "[#9CA3AF]P L A N   C R E A T E D[/#9CA3AF]", classes="output-label"
        )
        yield SectionRule(classes="divider-rule plan-created-rule")
        with VerticalScroll(id="plan-result-scroll"):
            with Container(id="plan-result-grid"):
                for row in self.ROWS:
                    yield Static("", id=f"plan-label-{row}", classes="plan-label")
                    if row in {"steps", "requested"}:
                        yield TodoList(
                            id=f"plan-value-{row}", classes="plan-value todo-list"
                        )
                    else:
                        yield Static("", id=f"plan-value-{row}", classes="plan-value")

    def show_plan(
        self,
        plan: TaskPlan,
        source: str | None = None,
        requested_items: list[str] | None = None,
    ) -> None:
        requested_items = requested_items or []
        rows: dict[str, tuple[Text, Text | str | list[tuple[str, str]] | None]] = {
            "goal": (
                Text("Goal", style="#9CA3AF"),
                Text(_bound_text(plan.task, 600), style="#E5E7EB"),
            ),
            "source": (Text("Source", style="#9CA3AF"), source),
            "steps": (
                Text(f"Proposed Steps ({len(plan.steps)})", style="#9CA3AF"),
                [(step.identifier, step.description) for step in plan.steps],
            ),
            "requested": (
                Text(f"Requested items ({len(requested_items)})", style="#9CA3AF"),
                [(str(index + 1), item) for index, item in enumerate(requested_items)],
            ),
            "safety": (
                Text("Safety", style="#9CA3AF"),
                Text(
                    "non-executing · no file changes · no commands run",
                    style="#E5E7EB",
                ),
            ),
            "next": (
                Text("Next Action", style="#9CA3AF"),
                Text(
                    "Review proposed plan. Use /edit or /test for approved execution.",
                    style="#E5E7EB",
                ),
            ),
        }
        for row, (label_value, value) in rows.items():
            label = self.query_one(f"#plan-label-{row}", Static)
            widget = self.query_one(f"#plan-value-{row}")
            visible = value is not None and (
                row != "requested" or bool(requested_items)
            )
            label.display = visible
            widget.display = visible
            if not visible:
                continue
            label.update(label_value)
            if isinstance(widget, TodoList):
                widget.set_items(value)  # type: ignore[arg-type]
            else:
                widget.update(value)  # type: ignore[arg-type]
        self._content_text = format_plan_result(plan, requested_items)
        self.call_after_refresh(self._sync_footer)

    def _sync_footer(self) -> None:
        self.app.screen.update_plan_footer(
            self.query_one("#plan-result-scroll", VerticalScroll).max_scroll_y > 0
        )

    @property
    def content_text(self) -> str:
        return getattr(self, "_content_text", "")


def _bound_text(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: max(0, limit - 1)].rstrip() + "…"


class GoalResult:
    def __init__(self, goal: str, method: str = "heuristic") -> None:
        self.goal = goal
        self.method = method


class PasteTokenHighlighter(Highlighter):
    """Styles collapsed Home-composer paste references, never pasted body."""

    def highlight(self, text: Text) -> None:
        for match in re.finditer(r"\[Pasted [\d,]+ chars\]", text.plain):
            text.stylize("#89B4FA on #343A45", match.start(), match.end())


CONDITIONAL_GOAL_PREFIXES = (
    "if",
    "when",
    "unless",
    "assuming",
    "note",
    "otherwise",
    "also",
    "jika",
    "kalau",
    "apabila",
    "catatan",
)
GOAL_VERBS = (
    "build",
    "create",
    "fix",
    "add",
    "implement",
    "refactor",
    "redesign",
    "write",
    "update",
    "analyze",
    "review",
    "test",
    "verify",
    "migrate",
    "remove",
    "optimize",
    "buat",
    "perbaiki",
    "tambah",
    "tambahkan",
    "ubah",
    "hapus",
    "analisis",
    "rapikan",
    "kerjakan",
)


def _clean_markdown_line(line: str) -> str:
    """Remove leading Markdown syntax, preserving token-internal # and *."""
    line = re.sub(r"^\s{0,3}(?:>\s*)+", "", line)
    line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
    line = re.sub(r"^\s*[-+*]\s+(?:\[[ xX]\]\s+)?", "", line)
    return re.sub(r"^\s*(?:\d+[.)]|§\s*\d+)\s+", "", line).strip()


def _goal_sentence(value: str) -> str:
    return " ".join(value.split())


def _is_conditional_goal(value: str) -> bool:
    return bool(re.match(rf"^({'|'.join(CONDITIONAL_GOAL_PREFIXES)})\b", value, re.I))


def outline_items(text: str) -> list[str]:
    """Extract bounded display-only prompt outline; never interprets prompt text."""
    clean = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    clean = "".join(char for char in clean if char >= " " or char in "\n\t")
    lines = clean.splitlines()
    heading_groups: list[tuple[int, list[str]]] = []
    for level in (1, 2, 3):
        pattern = rf"^\s*{'#' * level}(?!#)\s+"
        group = [line for line in lines if re.match(pattern, line)]
        if level == 1 and group:
            group = group[1:]
        if level == 2 and any(re.match(r"^\s*#(?!#)\s+", line) for line in lines):
            first_h1 = next(
                i for i, line in enumerate(lines) if re.match(r"^\s*#(?!#)\s+", line)
            )
            if first_h1 + 1 < len(lines) and re.match(pattern, lines[first_h1 + 1]):
                group.remove(lines[first_h1 + 1])
        heading_groups.append((level, group))
    viable_headings = [
        (len(group), -level, group)
        for level, group in heading_groups
        if len(group) >= 3
    ]

    list_groups: list[list[str]] = []
    current: list[str] = []
    current_style = ""
    for line in lines:
        match = re.match(r"^(\s{0,1})(\d+[.)]|[-*])\s+(?:\[[ xX]\]\s+)?", line)
        if match:
            style = "number" if match.group(2)[0].isdigit() else "bullet"
            if current and style != current_style:
                list_groups.append(current)
                current = []
            current_style = style
            current.append(line)
        elif current and line.strip() and len(line) - len(line.lstrip()) > 1:
            current.append(line)
        elif current:
            list_groups.append(current)
            current = []
    if current:
        list_groups.append(current)
    selected = (
        max(viable_headings)[2]
        if viable_headings
        else max(list_groups, key=len, default=[])
    )
    results: list[str] = []
    seen: set[str] = set()
    for line in selected:
        if not re.match(
            r"^(?:\s{0,1}#{1,3}\s+|\s{0,1}\d+[.)]\s+|\s{0,1}[-*]\s+(?:\[[ xX]\]\s+)?)",
            line,
        ):
            if results:
                results[-1] = _bound_text(f"{results[-1]} {line.strip()}", 200)
            continue
        item = _clean_markdown_line(line)
        item = _bound_text(item, 200)
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            results.append(item)
        if len(results) == 50:
            break
    return results


def detect_goal(text: str) -> GoalResult:
    """Extract bounded prompt goal, ignoring conditional and meta statements."""
    clean = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    clean = "".join(char for char in clean if char >= " " or char in "\n\t")
    raw_lines = clean.splitlines()
    first_section = next(
        (
            index
            for index, line in enumerate(raw_lines)
            if re.match(r"^\s*(?:#{1,6}\s*)?\d+[.)]", line)
        ),
        len(raw_lines),
    )
    lines = [_clean_markdown_line(line) for line in raw_lines]
    markers = (
        "goal",
        "objective",
        "primary objective",
        "task",
        "purpose",
        "aim",
        "target",
        "tujuan",
        "sasaran",
        "tugas",
        "permintaan",
    )
    for index, line in enumerate(lines[: min(40, first_section)]):
        match = re.match(rf"^({'|'.join(markers)})\s*:\s*(.*)$", line, re.I)
        if match:
            next_line = next((item for item in lines[index + 1 :] if item), "")
            candidate = _goal_sentence(match.group(2) or next_line)
            if candidate and not _is_conditional_goal(candidate):
                return GoalResult(_truncate_goal(candidate))

    headings = [
        _goal_sentence(line) for line in raw_lines if re.match(r"^\s*#{2,3}\s+", line)
    ]
    h1_index = next(
        (index for index, line in enumerate(raw_lines) if re.match(r"^\s*#\s+", line)),
        -1,
    )
    if h1_index >= 0:
        immediate = next(
            (
                _goal_sentence(_clean_markdown_line(line))
                for line in raw_lines[h1_index + 1 :]
                if re.match(r"^\s*#{2,3}\s+", line)
            ),
            "",
        )
        if immediate and not _is_conditional_goal(immediate):
            return GoalResult(_truncate_goal(immediate))
    if headings:
        candidate = headings[0]
        if candidate and not _is_conditional_goal(candidate):
            return GoalResult(_truncate_goal(candidate))
    if h1_index >= 0:
        candidate = _goal_sentence(_clean_markdown_line(raw_lines[h1_index]))
        if candidate and not _is_conditional_goal(candidate):
            return GoalResult(_truncate_goal(candidate))

    paragraphs = []
    for raw_paragraph in re.split(r"\n\s*\n", clean):
        paragraph_lines = [
            _clean_markdown_line(line)
            for line in raw_paragraph.splitlines()
            if line.strip()
        ]
        if paragraph_lines:
            paragraphs.append(_goal_sentence(" ".join(paragraph_lines)))
    for paragraph in paragraphs[:1]:
        paragraph = re.sub(
            r"^(?:context|background|konteks)\s*:\s*", "", paragraph, flags=re.I
        )
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            if sentence and not _is_conditional_goal(sentence):
                return GoalResult(_truncate_goal(sentence))
    for paragraph in paragraphs[:2]:
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            if not _is_conditional_goal(sentence) and re.search(
                rf"\b({'|'.join(GOAL_VERBS)})\b", sentence, re.I
            ):
                return GoalResult(_truncate_goal(sentence))
    fallback = next(
        (line for line in lines if line and not _is_conditional_goal(line)), ""
    )
    return GoalResult(_truncate_goal(fallback, empty_limit=120))


def _truncate_goal(value: str, empty_limit: int = 300) -> str:
    clean = " ".join(value.split())
    if len(clean) <= empty_limit:
        return clean
    return clean[:empty_limit].rstrip() + "…"


class ComposerInput(Input):
    """Home-only composer which keeps long paste bodies in session memory."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("highlighter", PasteTokenHighlighter())
        super().__init__(*args, **kwargs)
        self.paste_buffer: dict[str, str] = {}
        self.paste_count = 0
        self.paste_notice = ""

    def on_paste(self, event: events.Paste) -> None:
        event.prevent_default()
        event.stop()
        clean = re.sub(
            r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\a]*(?:\a|\x1b\\))", "", event.text
        )
        clean = clean.replace("\r\n", "\n").replace("\r", "\n")
        clean = "".join(char for char in clean if char >= " " or char in "\n\t")
        capped = len(clean) > 50_000
        clean = clean[:50_000]
        if len(clean) <= 200 and "\n" not in clean:
            self.insert_text_at_cursor(clean)
            return
        if sum(map(len, self.paste_buffer.values())) + len(clean) > 100_000:
            self.paste_notice = "Too much pasted text."
            self._update_notice()
            return
        self.paste_count += 1
        token = f"[Pasted {len(clean):,} chars]"
        self.paste_buffer[token] = clean
        self.insert_text_at_cursor(token)
        self.paste_notice = "Paste truncated to 50,000 chars." if capped else ""
        self._update_notice()

    def _update_notice(self) -> None:
        notice = self.screen.query("#paste-notice")
        if notice:
            notice.first(Static).update(self.paste_notice)

    def expanded_value(self) -> tuple[str, bool, int, int]:
        value = self.value
        pasted = False
        chars = 0
        lines = 0
        for token, body in self.paste_buffer.items():
            if token in value:
                value = value.replace(token, body)
                pasted = True
                chars += len(body)
                lines += body.count("\n") + 1
        return value, pasted, chars, lines


SLASH_COMMAND_REGISTRY: tuple[tuple[str, str], ...] = (
    ("/analyze", "analyze"),
    ("/ask", "context"),
    ("/edit", "edit"),
    ("/test", "test"),
    ("/verify", "verify"),
    ("/history", "history"),
    ("/replay", "replay"),
    ("/ai", "ai"),
    ("/settings", "settings"),
    ("/help", "help"),
    ("/pipeline", "pipeline"),
)

SLASH_COMMANDS: tuple[str, ...] = tuple(cmd for cmd, _ in SLASH_COMMAND_REGISTRY)
CONTENT_MAX = 100
HOME_HERO_CONTENT_MAX = 80

STATE_A_FOOTER = (
    "[bold #89B4FA]/[/bold #89B4FA] [#9CA3AF]commands[/#9CA3AF]   "
    "[bold #89B4FA]enter[/bold #89B4FA] [#9CA3AF]create plan[/#9CA3AF]   "
    "[bold #9CA3AF]ctrl+c exit[/bold #9CA3AF]"
)
STATE_B_FOOTER = (
    "[bold #89B4FA]/[/bold #89B4FA] [#9CA3AF]commands[/#9CA3AF]   "
    "[bold #89B4FA]n[/bold #89B4FA] [#9CA3AF]new plan[/#9CA3AF]   "
    "[bold #89B4FA]esc[/bold #89B4FA] [#9CA3AF]input[/#9CA3AF]   "
    "[bold #9CA3AF]ctrl+c exit[/bold #9CA3AF]"
)
FEATURE_FOOTER = (
    "[bold #89B4FA]tab[/bold #89B4FA] [#9CA3AF]focus[/#9CA3AF]   "
    "[bold #89B4FA]enter[/bold #89B4FA] [#9CA3AF]run[/#9CA3AF]   "
    "[bold #89B4FA]esc[/bold #89B4FA] [#9CA3AF]home[/#9CA3AF]   "
    "[bold #9CA3AF]ctrl+c exit[/bold #9CA3AF]"
)

LARGE_GLYPHS = {
    "Z": ["███████╗", "╚══███╔╝", "  ███╔╝ ", " ███╔╝  ", "███████╗", "╚══════╝"],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "R": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "G": [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "N": [
        "███╗   ██╗",
        "████╗  ██║",
        "██╔██╗ ██║",
        "██║╚██╗██║",
        "██║ ╚████║",
        "╚═╝  ╚═══╝",
    ],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "X": ["██╗  ██╗", "╚██╗██╔╝", " ╚███╔╝ ", " ██╔██╗ ", "██╔╝ ██╗", "╚═╝  ╚═╝"],
}
COMPACT_GLYPHS = {
    "Z": ["█████", "   █ ", "  █  ", " █   ", "█████"],
    "E": ["█████", "█    ", "████ ", "█    ", "█████"],
    "R": ["████ ", "█   █", "████ ", "█  █ ", "█   █"],
    "O": [" ███ ", "█   █", "█   █", "█   █", " ███ "],
    "A": [" ███ ", "█   █", "█████", "█   █", "█   █"],
    "G": [" ████", "█    ", "█  ██", "█   █", " ███ "],
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "T": ["█████", "  █  ", "  █  ", "  █  ", "  █  "],
    "X": ["█   █", " █ █ ", "  █  ", " █ █ ", "█   █"],
}


def make_wordmark_rows(glyphs: dict[str, list[str]], separator: str) -> tuple[str, ...]:
    return tuple(
        separator.join(glyphs[char][row] for char in "ZEROAGENT")
        + "   "
        + glyphs["X"][row]
        for row in range(len(glyphs["Z"]))
    )


WORDMARK_ROWS = make_wordmark_rows(COMPACT_GLYPHS, " ")
LARGE_WORDMARK_ROWS = make_wordmark_rows(LARGE_GLYPHS, "")
WORDMARK_FALLBACK = "Z E R O A G E N T   X"
WORDMARK_COLORS = ("#A6C8FF", "#9BBFFC", "#89B4FA", "#7AA5EC", "#6F9AE0")


class WordmarkView(Static):
    can_focus = False

    def on_mount(self) -> None:
        self.update_content()

    def on_resize(self, event: events.Resize) -> None:
        self.update_content()

    def update_content(self) -> None:
        w = self.app.size.width if self.app else 80
        if os.environ.get("ZEROAGENT_LOGO", "").lower() == "text" or w < 64:
            self.update(f"[bold #89B4FA]{WORDMARK_FALLBACK}[/bold #89B4FA]")
            return
        rows = LARGE_WORDMARK_ROWS if w >= 92 else WORDMARK_ROWS
        colors = (
            ("#B9D4FF", "#A6C8FF", "#9BBFFC", "#89B4FA", "#7AA5EC", "#6F9AE0")
            if w >= 92
            else WORDMARK_COLORS
        )
        wordmark = Text(no_wrap=True, end="")
        for index, row in enumerate(rows):
            for char in row:
                wordmark.append(
                    char,
                    style=colors[index]
                    if char == "█"
                    else "#4F6F9F"
                    if char != " "
                    else None,
                )
            if index < len(rows) - 1:
                wordmark.append("\n")
        self.update(wordmark)


class DotField(Static):
    can_focus = False

    def __init__(self, position: str = "top", id: str | None = None) -> None:
        super().__init__(id=id)
        self.position = position

    def on_mount(self) -> None:
        self.update_dots()

    def on_resize(self, event: events.Resize) -> None:
        self.update_dots()

    def update_dots(self) -> None:
        if (
            self.id in {"home-dot-bottom", "feature-bottom-dots"}
            and self.app.size.width >= 120
            and self.app.size.height >= 24
            and (self.id == "feature-bottom-dots" or self.screen.has_class("state-b"))
        ):
            self.display = False
            return
        if os.environ.get("ZEROAGENT_NO_DECOR") == "1":
            self.display = False
            return
        h = self.app.size.height if self.app else 35
        if h < 30:
            self.display = False
            return
        self.display = True
        w = self.app.size.width if self.app else 80
        pat = ("· " * (w // 2 + 2))[:w]
        if self.position == "top":
            colors = ("#2A2F38", "#22262D", "#1B1E24")
        else:
            colors = ("#1B1E24", "#22262D", "#2A2F38")
        lines = [f"[{c}]{pat}[/{c}]" for c in colors]
        self.update("\n".join(lines))


class ProofPipeline(Static):
    can_focus = False

    def __init__(
        self,
        current: str | None = None,
        id: str | None = None,
        orientation: str = "horizontal",
    ) -> None:
        super().__init__(id=id)
        self.current = current
        self.orientation = orientation

    def on_mount(self) -> None:
        self.update_pipeline()

    def on_resize(self, event: events.Resize) -> None:
        self.update_pipeline()

    def update_pipeline(self) -> None:
        if (
            self.id == "home-pipeline"
            and self.screen.has_class("state-b")
            and self.app.size.width >= 120
            and self.app.size.height >= 24
        ):
            self.display = False
            return
        if os.environ.get("ZEROAGENT_NO_DECOR") == "1":
            self.display = False
            return
        w = self.app.size.width if self.app else 80
        if w < 60 and self.orientation == "horizontal":
            self.display = False
            return
        self.display = True
        steps = ["plan", "edit", "test", "verify"]
        rendered_parts = []
        for step in steps:
            diamond = "[bold #89B4FA]◇[/bold #89B4FA]"
            if self.current == step:
                text = f"[bold #89B4FA]{step}[/bold #89B4FA]"
            else:
                text = f"[#9CA3AF]{step}[/#9CA3AF]"
            rendered_parts.append(f"{diamond} {text}")
        rendered_proof = "[bold #89B4FA]◆[/bold #89B4FA] [#9CA3AF]proof[/#9CA3AF]"
        if self.orientation == "vertical":
            nodes = rendered_parts + [rendered_proof]
            self.update("\n[#343A45]│[/#343A45]\n".join(nodes))
        else:
            self.update(" ──── ".join(rendered_parts) + f" ──── {rendered_proof}")


class CommandChip(Static):
    can_focus = False

    def __init__(self, command: str, feature: str) -> None:
        cmd_name = command.lstrip("/")
        super().__init__(
            cmd_name,
            classes="command-chip",
        )
        self.command = command
        self.feature = feature

    def on_click(self) -> None:
        self.app.handle_slash(self.command)


class CommandChipsGrid(Container):
    can_focus = False

    def chip_columns(self) -> int:
        width = self.app.size.width if self.app else 80
        if width < 40:
            return 2
        if width < 60:
            return 3
        return 5

    def chip_rows(self) -> list[Horizontal]:
        columns = self.chip_columns()
        rows = []
        for start in range(0, len(SLASH_COMMAND_REGISTRY), columns):
            entries = SLASH_COMMAND_REGISTRY[start : start + columns]
            chips = []
            for index, (command, feature) in enumerate(entries):
                chip = CommandChip(command, feature)
                if index == len(entries) - 1:
                    chip.add_class("last-chip")
                chips.append(chip)
            rows.append(Horizontal(*chips, classes="command-chip-row"))
        return rows

    def compose(self) -> ComposeResult:
        yield from self.chip_rows()

    def on_mount(self) -> None:
        self._columns = self.chip_columns()

    async def on_resize(self, event: events.Resize) -> None:
        columns = self.chip_columns()
        if columns == self._columns:
            return
        self._columns = columns
        await self.remove_children()
        await self.mount(*self.chip_rows())


def format_plan_result(plan: TaskPlan, requested_items: list[str] | None = None) -> str:
    requested_items = requested_items or []
    steps = "\n".join(
        f"[ ] {step.identifier} {step.description}" for step in plan.steps
    )
    requested = "\n".join(
        f"[ ] {index + 1} {item}" for index, item in enumerate(requested_items)
    )
    parts = (
        "PLAN CREATED",
        f"Goal            {_bound_text(plan.task, 600)}",
        f"Proposed Steps ({len(plan.steps)})\n{steps}",
        f"Requested items ({len(requested_items)})\n{requested}" if requested else "",
        "Safety          non-executing · no file changes · no commands run",
        (
            "Next Action     Review proposed plan. Use /edit or /test for "
            "approved execution."
        ),
    )
    return "\n".join(part for part in parts if part)


@dataclass(frozen=True)
class SessionEvent:
    ts: str
    kind: str
    title: str
    detail: str = ""


TIME_W = 5
BLANK_TIME = " " * TIME_W
CONT_PREFIX = "      │ "
CONT_PREFIX_LAST = "        "
CONNECTOR = "      │"


def _log_wrap(value: str, width: int, limit: int = 3) -> list[str]:
    chunks = textwrap.wrap(
        value, width=width, break_long_words=False, break_on_hyphens=False
    )
    output: list[str] = []
    for chunk in chunks:
        output.extend(
            chunk[offset : offset + width] for offset in range(0, len(chunk), width)
        )
    if len(output) > limit:
        clipped = output[:limit]
        clipped[-1] = clipped[-1][: max(0, width - 1)].rstrip() + "…"
        return clipped
    return output


def render_log_lines(
    events: list[SessionEvent | tuple[str, str]], width: int
) -> list[Text]:
    """Render bounded Session Log rows in a fixed time/glyph/text grid."""
    if not events:
        return [
            Text("No activity yet.", style="#6B7280", no_wrap=True, overflow="crop")
        ]
    width = max(width, 9)
    text_width = max(1, width - 8)
    rows: list[Text] = []
    hide_connectors = os.environ.get("ZEROAGENT_NO_DECOR") == "1"
    normalized = [
        event
        if isinstance(event, SessionEvent)
        else SessionEvent(event[0], "event", event[1])
        for event in events
    ]
    for index, event in enumerate(normalized):
        is_last = index == len(normalized) - 1
        title = _bound_text(event.title, min(40, text_width))
        first_prefix = f"{event.ts:>{TIME_W}} ● "
        assert len(first_prefix) == len(CONT_PREFIX) == len(CONT_PREFIX_LAST) == 8
        row = Text(first_prefix + title, no_wrap=True, overflow="crop")
        row.stylize("#6B7280", 0, 5)
        row.stylize("#89B4FA" if index == 0 else "#4F6F9F", 6, 7)
        row.stylize("#E5E7EB", 8, len(row.plain))
        rows.append(row)
        for detail in (
            _log_wrap(_bound_text(event.detail, 200), text_width)
            if event.detail
            else []
        ):
            prefix = CONT_PREFIX_LAST if is_last or hide_connectors else CONT_PREFIX
            row = Text(prefix + detail, no_wrap=True, overflow="crop")
            row.stylize("#343A45", 6, 7)
            row.stylize("#9CA3AF", 8, len(row.plain))
            rows.append(row)
        if index < len(events) - 1 and not hide_connectors:
            row = Text(CONNECTOR, no_wrap=True, overflow="crop")
            row.stylize("#343A45", 6, 7)
            rows.append(row)
    return rows


class SessionLog(Static):
    can_focus = False

    def __init__(self) -> None:
        super().__init__(id="session-log")
        self.events: deque[SessionEvent] = deque(maxlen=200)

    def add(self, title: str, detail: str = "") -> None:
        from datetime import datetime

        self.events.appendleft(
            SessionEvent(
                datetime.now().strftime("%H:%M"), "event", title[:40], detail[:200]
            )
        )
        self.refresh_log()

    def on_resize(self, event: events.Resize) -> None:
        self.refresh_log()

    def on_mount(self) -> None:
        self.events = deque(self.app.session_events, maxlen=200)
        self.refresh_log()

    def refresh_log(self) -> None:
        width = self.content_size.width or self.region.width or 32
        lines = render_log_lines(list(self.events), width)
        text = Text("\n").join(lines)
        text.no_wrap = True
        text.overflow = "crop"
        self.update(text)


class FeatureWorkbench(Screen):
    BINDINGS: ClassVar = [
        ("escape", "back", "Home"),
        ("/", "palette", "Command Palette"),
        ("ctrl+c", "quit", "Quit"),
        ("q", "quit", "Quit"),
    ]

    feature_name: ClassVar[str] = "Feature"
    feature_title: ClassVar[str] = "Feature Title"
    feature_description: ClassVar[str] = "Feature description."
    pipeline_current: ClassVar[str | None] = None
    empty_output_text: ClassVar[str] = "No output available yet."

    def _sync_workbench_mode(self) -> None:
        size = self.app.size
        narrow = size.width < 120 or size.height < 24
        self.set_class(narrow, "narrow-workbench")
        pipelines = self.query("#side-panel ProofPipeline")
        if pipelines:
            pipeline = pipelines.first(ProofPipeline)
            pipeline.orientation = "horizontal" if narrow else "vertical"
            pipeline.update_pipeline()
        panels = self.query("#side-panel")
        if not narrow and panels:
            panels.first().styles.width = min(max(size.width // 5, 32), 44)

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_palette(self) -> None:
        self.app.push_screen(CommandPalette())

    def action_quit(self) -> None:
        self.app.run_worker(self.app.action_quit())

    def on_mount(self) -> None:
        self._sync_workbench_mode()
        self.app.emit_session_event(f"opened {self.feature_name}")
        inputs = self.query(Input)
        if inputs:
            inputs.first().focus()
            return
        primary = self.query("Button.btn-primary")
        if primary:
            primary.first(Button).focus()

    def on_resize(self, event: events.Resize) -> None:
        self._sync_workbench_mode()

    def compose(self) -> ComposeResult:
        yield DotField(position="top")
        with Horizontal(classes="feature-top-bar"):
            yield Static(
                f"[bold #89B4FA]ZEROAGENT X[/bold #89B4FA] "
                f"[#9CA3AF]›[/#9CA3AF] "
                f"[bold #E5E7EB]{self.feature_name}[/bold #E5E7EB]",
                classes="feature-breadcrumb",
            )
            yield Static(
                self.app.cwd_version_text(self.feature_name), classes="feature-version"
            )
        yield SectionRule(classes="divider-rule feature-rule")
        with Horizontal(id="workbench-body"):
            with Container(id="feature-main"):
                yield Static(
                    f"[bold #E5E7EB]{self.feature_title}[/bold #E5E7EB]",
                    classes="page-title",
                )
                yield Static(
                    f"[#9CA3AF]{self.feature_description}[/#9CA3AF]",
                    classes="page-subtitle",
                )

                info_rows = self.compose_info_rows()
                if info_rows:
                    with Container(id="info-card"):
                        for item in info_rows:
                            if len(item) == 3:
                                key, val, row_id = item
                                yield Static(
                                    f"[#9CA3AF]{key:<10}[/#9CA3AF] "
                                    f"[bold #E5E7EB]{val}[/bold #E5E7EB]",
                                    id=row_id,
                                    classes="info-card-row",
                                )
                            else:
                                key, val = item
                                yield Static(
                                    f"[#9CA3AF]{key:<10}[/#9CA3AF] "
                                    f"[bold #E5E7EB]{val}[/bold #E5E7EB]",
                                    classes="info-card-row",
                                )

                yield from self.compose_action_area()
                yield Static("[#9CA3AF]O U T P U T[/#9CA3AF]", classes="output-label")
                yield SectionRule(classes="divider-rule output-rule")
                with VerticalScroll(id="output-container"):
                    yield OutputPanel(self.empty_output_text, id="result")
            with Container(id="side-panel"):
                yield Static("SESSION LOG", classes="side-title")
                yield SectionRule(classes="divider-rule side-rule")
                yield SessionLog()
                yield Static("PIPELINE", classes="side-title")
                yield SectionRule(classes="divider-rule side-rule")
                yield ProofPipeline(
                    current=self.pipeline_current, orientation="vertical"
                )
        yield DotField(position="bottom", id="feature-bottom-dots")
        yield ContextualFooter(FEATURE_FOOTER)

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return []

    def compose_action_area(self) -> ComposeResult:
        return []

    def show_result(
        self,
        text: str | Syntax,
        kind: str = "result",
        title: str = "",
    ) -> None:
        default_titles = {
            "result": "RESULT",
            "error": "ERROR",
            "approval": "APPROVAL REQUIRED",
            "evidence": "STRUCTURAL EVIDENCE",
            "diff": "UNIFIED DIFF",
            "test": "TEST EXECUTION",
            "history": "AUDIT HISTORY",
        }
        t = title or default_titles.get(kind, "INFORMATION")
        panels = self.query("#result")
        if panels:
            panels.first(OutputPanel).show(text, title=t, kind=kind)


FeatureScreen = FeatureWorkbench
BaseScreen = FeatureWorkbench


class HomeScreen(Screen):
    BINDINGS: ClassVar = [
        ("escape", "escape", "Back to input"),
        ("n", "new_plan", "New plan"),
        ("/", "palette", "Command Palette"),
        ("ctrl+c", "quit", "Quit"),
        ("q", "quit", "Quit"),
        ("1", "open_1", ""),
        ("2", "open_2", ""),
        ("3", "open_3", ""),
        ("4", "open_4", ""),
        ("5", "open_5", ""),
        ("6", "open_6", ""),
        ("7", "open_7", ""),
        ("8", "open_8", ""),
        ("9", "open_9", ""),
        ("pageup", "scroll_result_up", ""),
        ("pagedown", "scroll_result_down", ""),
    ]

    def compose(self) -> ComposeResult:
        yield DotField(position="top", id="home-dot-top")
        yield WordmarkView(id="state-a-wordmark")
        with Horizontal(id="state-b-header"):
            yield Static(
                "[bold #89B4FA]ZEROAGENT X[/bold #89B4FA] "
                "[#9CA3AF]›[/#9CA3AF] [bold #E5E7EB]Plan[/bold #E5E7EB]",
                id="state-b-brand",
            )
            yield Static(self.app.cwd_version_text("Plan"), id="state-b-version")
        yield Static(self.app.cwd_version_text(""), id="state-a-cwd")
        yield SectionRule(id="state-b-rule", classes="divider-rule")
        with Horizontal(id="home-workbench-body"):
            with VerticalScroll(id="home-scroll"):
                with Container(id="home-inner"):
                    # State A Wordmark, Tagline, Subtitle
                    yield Static(
                        "[bold #E5E7EB]Don't Just Run AI. Prove It Works."
                        "[/bold #E5E7EB]",
                        id="state-a-tagline",
                    )
                    yield Static(
                        "[#9CA3AF]Local-first · Proof-driven · Open source[/#9CA3AF]",
                        id="state-a-subtitle",
                    )

                    # Composer (the ONLY bordered element on Home)
                    yield ComposerInput(
                        placeholder="Describe what you want to accomplish...",
                        id="planning-task",
                    )
                    yield Static(
                        "[#9CA3AF]Plan · non-executing[/#9CA3AF]",
                        id="planning-hint",
                    )
                    yield Static("", id="paste-notice")

                    # State A Hints & Command Chips
                    hint_text = (
                        "[bold #E5E7EB]enter[/bold #E5E7EB] "
                        "[#9CA3AF]create plan[/#9CA3AF]"
                    )
                    yield Static(hint_text, id="home-hint-line")
                    yield CommandChipsGrid(id="home-chips")

                    # State B Result & Hints
                    yield PlanResultView("", id="plan-result")
                    yield Static("", id="state-b-actions")
                    yield Static("", id="state-b-commands")

                    # ProofPipeline on Home State A
                    yield ProofPipeline(id="home-pipeline")

                    # Status Line (One line above footer)
                    ws_name = self.app.workspace.name or "zeroagent-x"
                    status_text = (
                        f"[#9CA3AF]{ws_name} · Proof Ready · AI Not connected[/#9CA3AF]"
                    )
                    yield Static(status_text, id="home-status")

            with Container(id="home-side-panel"):
                yield Static("SESSION LOG", classes="side-title")
                yield SectionRule(classes="divider-rule side-rule")
                yield SessionLog()
                yield Static("PIPELINE", classes="side-title")
                yield SectionRule(classes="divider-rule side-rule")
                yield ProofPipeline(id="home-side-pipeline", orientation="vertical")

        yield DotField(position="bottom", id="home-dot-bottom")
        yield ContextualFooter(STATE_A_FOOTER)

    def set_state_a(self) -> None:
        self.app.home_plan = None
        self.remove_class("state-b")
        self.query_one("#state-a-cwd", Static).display = True
        scroll = self.query_one("#home-scroll", VerticalScroll)
        scroll.remove_class("state-b")
        self.query_one("#plan-result", PlanResultView).display = False
        self.query_one("#planning-hint", Static).update(
            "[#9CA3AF]Plan · non-executing[/#9CA3AF]"
        )
        for df in self.query(DotField):
            df.update_dots()
        for pp in self.query(ProofPipeline):
            pp.update_pipeline()
        chips = self.query(CommandChipsGrid)
        if chips:
            chips.first().display = True
        footers = self.query(ContextualFooter)
        if footers:
            footers.first().update_text(STATE_A_FOOTER)

    def set_state_b(self) -> None:
        self.add_class("state-b")
        self.query_one("#state-a-cwd", Static).display = False
        scroll = self.query_one("#home-scroll", VerticalScroll)
        scroll.add_class("state-b")
        if self.app.home_plan:
            result = self.query_one("#plan-result", PlanResultView)
            result.display = True
            if not getattr(result, "_content_text", ""):
                result._content_text = self.app.home_plan
        self.query_one("#planning-hint", Static).update(
            "[#9CA3AF]Plan · non-executing[/#9CA3AF]"
        )
        for df in self.query(DotField):
            df.update_dots()
        for pp in self.query(ProofPipeline):
            pp.update_pipeline()
        size = self.app.size
        narrow = size.width < 120 or size.height < 24
        self.set_class(narrow, "narrow-state-b")
        panel = self.query("#home-side-panel")
        if not narrow and panel:
            panel.first().styles.width = min(max(size.width // 5, 32), 44)
        chips = self.query(CommandChipsGrid)
        if chips:
            chips.first().display = False
        footers = self.query(ContextualFooter)
        if footers:
            footers.first().update_text(STATE_B_FOOTER)

    def on_resize(self, event: events.Resize) -> None:
        if self.has_class("state-b"):
            self.set_state_b()

    def on_mount(self) -> None:
        if self.app.home_plan:
            self.set_state_b()
        else:
            self.set_state_a()
        self.query_one("#planning-task", Input).focus()

    def on_screen_resume(self) -> None:
        if self.app.home_plan:
            self.set_state_b()
        else:
            self.set_state_a()
        self.query_one("#planning-task", Input).focus()

    def action_escape(self) -> None:
        self.query_one("#planning-task", Input).focus()

    def action_scroll_result_up(self) -> None:
        if self.has_class("state-b"):
            self.query_one("#plan-result-scroll", VerticalScroll).scroll_page_up()

    def action_scroll_result_down(self) -> None:
        if self.has_class("state-b"):
            self.query_one("#plan-result-scroll", VerticalScroll).scroll_page_down()

    def update_plan_footer(self, overflowing: bool) -> None:
        footer = self.query(ContextualFooter)
        if footer and self.has_class("state-b"):
            suffix = (
                "   [bold #89B4FA]pgup/pgdn[/bold #89B4FA] [#9CA3AF]scroll[/#9CA3AF]"
                if overflowing
                else ""
            )
            footer.first().update_text(STATE_B_FOOTER + suffix)

    def action_new_plan(self) -> None:
        if self.app.focused == self.query_one("#planning-task", Input):
            return
        inp = self.query_one("#planning-task", Input)
        inp.value = ""
        self.set_state_a()
        inp.focus()

    @on(Input.Submitted, "#planning-task")
    def on_task_submit(self) -> None:
        composer = self.query_one("#planning-task", ComposerInput)
        task, pasted, chars, lines = composer.expanded_value()
        task = task.strip()
        if not task:
            self.query_one("#planning-hint", Static).update(
                "[#E5C07B]Describe a task first.[/#E5C07B]"
            )
            return
        if pasted:
            self.create_plan(task, pasted=True, chars=chars, lines=lines)
        elif task == "/":
            self.query_one("#planning-task", Input).value = ""
            self.action_palette()
        elif task.startswith("/"):
            self.query_one("#planning-task", Input).value = ""
            self.app.handle_slash(task)
        else:
            self.create_plan(task, pasted=pasted, chars=chars, lines=lines)

    def create_plan(
        self, task: str, pasted: bool = False, chars: int = 0, lines: int = 0
    ) -> None:
        if not task:
            self.query_one("#planning-hint", Static).update(
                "[#E5C07B]Describe a task first.[/#E5C07B]"
            )
            return
        try:
            goal = detect_goal(task).goal if pasted else task
            plan = validate_plan(create_plan(goal, self.app.workspace))
            requested_items = outline_items(task) if pasted else []
            self.app.home_plan = format_plan_result(plan, requested_items)
            source = (
                f"Pasted prompt · {chars:,} chars · {lines:,} lines" if pasted else None
            )
            self.query_one("#plan-result", PlanResultView).show_plan(
                plan, source, requested_items
            )
            self.app.emit_session_event("plan created", _bound_text(goal, 200), "plan")
            self.set_state_b()
        except Exception as error:
            self.app.home_plan = f"Planning failed: {error}"
            self.set_state_b()

    def action_palette(self) -> None:
        self.app.push_screen(CommandPalette())

    def action_quit(self) -> None:
        self.app.run_worker(self.app.action_quit())

    def _open(self, index: int) -> None:
        self.app.open_feature(MENU_ITEMS[index][3])

    def action_open_1(self) -> None:
        self._open(0)

    def action_open_2(self) -> None:
        self._open(1)

    def action_open_3(self) -> None:
        self._open(2)

    def action_open_4(self) -> None:
        self._open(3)

    def action_open_5(self) -> None:
        self._open(4)

    def action_open_6(self) -> None:
        self._open(5)

    def action_open_7(self) -> None:
        self._open(6)

    def action_open_8(self) -> None:
        self._open(7)

    def action_open_9(self) -> None:
        self._open(8)


class AgentScreen(FeatureScreen):
    """Explicit route, run, and proof workflow over shared local backend APIs."""

    feature_name = "Agent"
    feature_title = "Agent Workspace"
    feature_description = (
        "Route is non-executing. Run uses only permitted registered local capabilities."
    )
    empty_output_text = "Enter task, Route Task, then explicitly Run Agent."
    task_limit = 600

    def __init__(self) -> None:
        super().__init__()
        self.route: RoutingDecision | None = None
        self.route_task_text: str | None = None
        self.route_workspace: Path | None = None
        self.execution: tuple[RoutingDecision, object] | None = None
        self.running = False

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [("WORKSPACE", str(self.app.workspace))]

    def compose_action_area(self) -> ComposeResult:
        yield Input("", placeholder="Analyze this repository", id="agent-task")
        yield Static(
            "Tasks are not terminal commands. "
            "Use operating-system Terminal for CLI commands.",
            classes="page-subtitle",
        )
        with Horizontal(classes="action-row"):
            yield Button("Route Task", id="btn-route", classes="btn-primary")
            yield Button(
                "Run Agent", id="btn-run", classes="btn-secondary", disabled=True
            )
            yield Button(
                "Verify Results",
                id="btn-verify",
                classes="btn-secondary",
                disabled=True,
            )

    def task_text(self) -> str | None:
        value = self.query_one("#agent-task", Input).value
        if len(value) > self.task_limit:
            self.show_result("Task exceeds 600-character limit.", "error")
            return None
        if not value.strip() or any(
            ord(char) < 32 and char not in "\t\n" for char in value
        ):
            self.show_result(
                "Enter non-empty task text without control characters.", "error"
            )
            return None
        return " ".join(value.split())

    def _invalidate(self) -> None:
        self.route = None
        self.route_task_text = None
        self.route_workspace = None
        self.execution = None
        self.query_one("#btn-run", Button).disabled = True
        self.query_one("#btn-verify", Button).disabled = True

    @on(Input.Changed, "#agent-task")
    def invalidate_on_task_change(self) -> None:
        if self.route or self.execution:
            self._invalidate()
            self.show_result("Task changed. Route again before running.", "warning")

    @on(Button.Pressed, "#btn-route")
    def route_agent_task(self) -> None:
        if self.running:
            return
        task = self.task_text()
        if task is None:
            return
        self._invalidate()
        decision, _ = route_task(task)
        self.route = decision
        self.route_task_text = task
        self.route_workspace = self.app.workspace.resolve()
        allowed = decision.decision == "allowed"
        self.query_one("#btn-run", Button).disabled = not allowed
        self.show_result(
            "ROUTING COMPLETE\n\n"
            f"Category:   {escape(decision.classification.category)}\n"
            f"Decision:   {escape(decision.decision.upper())}\n"
            f"Capability: {escape(decision.selected_capability or 'none')}\n"
            f"Reason:     {escape(decision.reason)}\n"
            "Execution: NOT STARTED",
            "result" if allowed else "warning",
        )
        self.app.emit_session_event(
            "task routed", decision.classification.category, "agent"
        )

    def _fresh_route(self, task: str) -> bool:
        return (
            self.route is not None
            and self.route.decision == "allowed"
            and self.route_task_text == task
            and self.route_workspace == self.app.workspace.resolve()
        )

    @on(Button.Pressed, "#btn-run")
    async def run_agent_task(self) -> None:
        if self.running:
            return
        task = self.task_text()
        if task is None or not self._fresh_route(task):
            self._invalidate()
            self.show_result(
                "Route is stale. Route task again before running.", "warning"
            )
            return
        self.running = True
        self.app.begin_agent_execution()
        self.query_one("#btn-run", Button).disabled = True
        self.show_result("Agent running. Registered local capability only.")
        self.app.emit_session_event(
            "agent started", self.route.selected_capability or "", "agent"
        )
        try:
            execution = await asyncio.to_thread(run_task, task, self.app.workspace)
            if not self._fresh_route(task):
                self.show_result(
                    "Workspace changed during execution. Result is stale.", "warning"
                )
                return
            self.execution = execution
            decision, result = execution
            self.query_one("#btn-verify", Button).disabled = False
            self.show_result(self._execution_text(decision, result))
            self.app.emit_session_event(
                "agent completed", decision.selected_capability or "", "agent"
            )
        except Exception as error:
            self.show_result(f"Agent execution failed: {escape(str(error))}", "error")
            self.app.emit_session_event("agent failed", type(error).__name__, "agent")
        finally:
            self.running = False
            self.app.finish_agent_execution()

    async def action_back(self) -> None:
        """Do not dispose Agent screen until its synchronous worker has settled."""
        if self.running:
            self.show_result("Agent is settling before navigation.", "warning")
            await self.app.wait_agent_settlement()
        self.app.pop_screen()

    def _execution_text(self, decision: RoutingDecision, result: object) -> str:
        lines = [
            "EXECUTION COMPLETE",
            "",
            f"Capability: {decision.selected_capability}",
            f"Workspace:  {escape(str(self.app.workspace))}",
        ]
        if hasattr(result, "file_count"):
            lines.extend(
                [
                    f"Files:      {result.file_count}",
                    f"Directories: {result.directory_count}",
                    f"Completeness: {'Complete' if result.complete else 'Incomplete'}",
                ]
            )
        else:
            lines.append(
                "Result: supported local capability completed; "
                "structured proof may be incomplete."
            )
        return "\n".join(lines)

    @on(Button.Pressed, "#btn-verify")
    def verify_agent_result(self) -> None:
        task = self.task_text()
        if not self.execution or task is None or not self._fresh_route(task):
            self._invalidate()
            self.show_result(
                "No current execution evidence. Route and run task again.", "warning"
            )
            return
        decision, result = self.execution
        proof = verify_execution(decision, result, self.app.workspace)
        checks = "\n".join(
            f"- {check.check_id}: {check.status} — {escape(check.reason)}"
            for check in proof.checks
        )
        self.show_result(
            f"PROOF: {proof.overall_status}\n\n{checks}\n\n"
            "Structural verification does not guarantee semantic correctness.",
            "evidence" if proof.overall_status == "VERIFIED" else "warning",
        )
        self.app.emit_session_event(
            "verification completed", proof.overall_status, "agent"
        )


class AnalyzeScreen(FeatureScreen):
    feature_name = "Analyze"
    feature_title = "Analyze Repository"
    feature_description = (
        "Inspect repository structure, language breakdown, and bounded file metadata."
    )
    pipeline_current = None
    empty_output_text = (
        "No analysis yet. Select Analyze now to inspect project manifests."
    )

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("PROJECT", self.app.workspace.name or str(self.app.workspace)),
            ("PATH", str(self.app.workspace)),
        ]

    def compose_action_area(self) -> ComposeResult:
        with Horizontal(classes="action-row"):
            yield Button("▶ Analyze now", id="btn-analyze", classes="btn-primary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    @on(Button.Pressed, "#btn-analyze")
    def run_analysis(self) -> None:
        try:
            report = analyze_repository(self.app.workspace)
            langs = ", ".join(
                f"{x.language} ({x.percentage:.1f}%)" for x in report.languages[:6]
            )
            self.show_result(
                f"[bold #89B4FA]Analysis Complete[/bold #89B4FA]\n\n"
                f"Workspace:    {report.workspace_identifier}\n"
                f"Files:        {report.file_count}\n"
                f"Directories:  {report.directory_count}\n"
                f"Manifests:    {', '.join(report.manifests) or 'None'}\n"
                f"Languages:    {langs or 'None'}\n"
                f"Completeness: {'Complete' if report.complete else 'Partial'}"
            )
            self.app.emit_session_event(
                "analysis finished", f"{report.file_count} files", "analysis"
            )
        except Exception as error:
            self.show_result(f"Analysis failed: {error}", kind="error")
            self.app.emit_session_event("analysis failed", kind="analysis")


class ContextScreen(FeatureScreen):
    feature_name = "Ask"
    feature_title = "Ask About Repository"
    feature_description = (
        "Preview context; transfer source files only with explicit authorization."
    )
    pipeline_current = None
    empty_output_text = (
        "No conversation yet. Preview context or authorize before querying."
    )

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("WORKSPACE", self.app.workspace.name or str(self.app.workspace)),
            ("POLICY", "Local-first · Offline"),
            ("GATE", "Explicit authorization required"),
        ]

    def compose_action_area(self) -> ComposeResult:
        yield Input(
            placeholder="Ask a question about this repository...", id="question"
        )
        with Horizontal(classes="action-row"):
            yield Button("▶ Preview context", id="btn-preview", classes="btn-primary")
            yield Button("Authorize context", id="btn-ask", classes="btn-secondary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    @on(Button.Pressed)
    def run_context(self, event: Button.Pressed) -> None:
        q = self.query_one("#question", Input).value.strip()
        if not q:
            self.show_result("Enter a question first.", kind="error")
            self.app.emit_session_event("ask failed", kind="ask")
            return
        try:
            if event.button.id == "btn-preview":
                rep = select_context(self.app.workspace, q)
                files = "\n".join(
                    f"  • {s.path} (score: {s.score})" for s in rep.selections
                )
                header = "[bold #89B4FA]Metadata-Only Preview:[/bold #89B4FA]\n"
                self.show_result(f"{header}{files or 'No safe candidates'}")
            elif event.button.id == "btn-ask":
                models = LocalAIService(load_settings()).models()
                if not models:
                    self._show_ask_error("No installed local Ollama models found.")
                    self.app.emit_session_event("ask failed", "no local model", "ask")
                    return
                report = build_context(self.app.workspace, q, allow_context=True)
                response = LocalAIService(load_settings()).ask(
                    context_prompt(report), models[0].identifier
                )
                refs = ", ".join(
                    f"{s.path}:{s.start_line}-{s.end_line}" for s in report.sources
                )
                self.show_result(
                    f"[bold #9CA3AF]QUESTION[/bold #9CA3AF]\n"
                    f"{_bound_text(q, 600)}\n\n"
                    "[bold #9CA3AF]ANSWER[/bold #9CA3AF]\n"
                    f"{response.response}\n\n"
                    "[bold #9CA3AF]STATUS[/bold #9CA3AF]\n"
                    f"Local model · Response received · {models[0].identifier}\n"
                    f"Sources: {refs or 'No source excerpts'}\n"
                    "[dim #FFCA65]Semantic correctness: unverified.[/dim #FFCA65]"
                )
                self.app.emit_session_event("ask answered", kind="ask")
        except Exception:
            self._show_ask_error("Unable to complete local Ollama request.")
            self.app.emit_session_event("ask failed", kind="ask")

    def _show_ask_error(self, detail: str) -> None:
        """Show bounded local-only Ask failures without provider internals."""
        self.show_result(
            f"{detail}\n\nNo cloud fallback was attempted.",
            kind="error",
            title="LOCAL AI UNAVAILABLE",
        )


class EditScreen(FeatureScreen):
    feature_name = "Edit"
    feature_title = "Safe Code Editing"
    feature_description = (
        "Review changes, unified diffs, exact digest approval & atomic rollback."
    )
    pipeline_current = "edit"
    empty_output_text = (
        "No patch proposal loaded. Load proposal to preview unified diff."
    )

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("WORKSPACE", self.app.workspace.name or str(self.app.workspace)),
            ("PROPOSAL", "Not loaded", "prop-status"),
            ("APPROVAL", "Required", "appr-status"),
        ]

    def compose_action_area(self) -> ComposeResult:
        yield Input(placeholder="Path to proposal JSON file...", id="proposal-path")
        yield Input(
            placeholder="Enter exact proposal digest to approve...", id="digest"
        )
        with Horizontal(classes="action-row"):
            btn_apply = Button("Apply patch", id="btn-apply", classes="btn-secondary")
            btn_apply.disabled = True
            yield Button("▶ Preview diff", id="btn-preview", classes="btn-primary")
            yield Button("Load proposal", id="btn-load", classes="btn-secondary")
            yield btn_apply
            yield Button("Approve digest", id="btn-approve", classes="btn-secondary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.proposal: PatchProposal | None = None
        self.approved = False

    @on(Button.Pressed)
    def run_edit(self, event: Button.Pressed) -> None:
        try:
            if event.button.id == "btn-load":
                p_path = Path(self.query_one("#proposal-path", Input).value.strip())
                self.proposal = load_proposal(p_path)
                self.approved = False
                self.query_one("#btn-apply", Button).disabled = True
                pid_short = self.proposal.proposal_id[:8]
                self.query_one("#prop-status", Static).update(
                    "[#9CA3AF]PROPOSAL  [/#9CA3AF] "
                    f"[bold #E5E7EB]{pid_short}[/bold #E5E7EB]"
                )
                self.query_one("#appr-status", Static).update(
                    "[#9CA3AF]APPROVAL  [/#9CA3AF] "
                    "[bold #E5E7EB]Required[/bold #E5E7EB]"
                )
                self.show_result(
                    f"Proposal Loaded:\n"
                    f"• Digest: {self.proposal.digest}\n"
                    f"• Changes: {len(self.proposal.changes)} file(s)\n"
                    f"• Explanation: {self.proposal.explanation}"
                )
            elif event.button.id == "btn-preview":
                if not self.proposal:
                    raise ValueError("Load a proposal first.")
                diff = preview_patch(self.proposal, self.app.workspace)
                self.show_result(
                    Syntax(diff, "diff", line_numbers=True, word_wrap=True),
                    kind="diff",
                    title="UNIFIED DIFF",
                )
                self.app.emit_session_event("patch previewed", kind="edit")
            elif event.button.id == "btn-approve":
                if not self.proposal:
                    raise ValueError("Load a proposal first.")
                d = self.query_one("#digest", Input).value.strip()
                if d != self.proposal.digest:
                    raise ValueError("Exact proposal digest is required.")
                self.approved = True
                self.query_one("#btn-apply", Button).disabled = False
                self.query_one("#appr-status", Static).update(
                    "[#9CA3AF]APPROVAL  [/#9CA3AF] "
                    "[bold #89B4FA]Approved[/bold #89B4FA]"
                )
                self.show_result(
                    "Exact proposal digest approved. Press 'Apply patch' to write."
                )
                self.app.emit_session_event(
                    "patch approved", self.proposal.digest[:8], "edit"
                )
            elif event.button.id == "btn-apply":
                if not self.proposal or not self.approved:
                    raise ValueError("Application blocked: exact approval required.")
                approval = approve(self.proposal, self.app.workspace)
                recovery = (
                    Path.home() / ".zeroagent" / "recovery" / self.proposal.proposal_id
                )
                result = apply_patch(
                    self.proposal, approval, self.app.workspace, recovery
                )
                proof = verify_execution(
                    None, self.app.patch_evidence(result), self.app.workspace
                )
                self.approved = False
                self.query_one("#btn-apply", Button).disabled = True
                self.query_one("#appr-status", Static).update(
                    "[#9CA3AF]APPROVAL  [/#9CA3AF] "
                    "[bold #E5E7EB]Executed[/bold #E5E7EB]"
                )
                files_str = ", ".join(result.applied_paths)
                self.show_result(
                    f"Patch Applied: {files_str}\n"
                    f"Recovery Path: {result.recovery_path}\n"
                    f"Proof Status: {proof.overall_status}\n"
                    "Notice: Tests have not run.",
                    kind="evidence",
                    title="PATCH EXECUTION EVIDENCE",
                )
                self.app.emit_session_event("patch applied", kind="edit")
        except Exception as error:
            self.show_result(f"Editing error: {error}", kind="error")
            self.app.emit_session_event("patch failed", kind="edit")


class TestScreen(FeatureScreen):
    __test__ = False
    feature_name = "Test"
    feature_title = "Run Controlled Tests"
    feature_description = (
        "Execute allowlisted pytest suite under strict boundaries and exact approval."
    )
    pipeline_current = "test"
    empty_output_text = (
        "No tests executed. Create specification and approve digest to run."
    )

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("RUNNER", "pytest (allowlisted)"),
            ("SPEC", "Not generated", "spec-status"),
            ("APPROVAL", "Required", "test-appr-status"),
        ]

    def compose_action_area(self) -> ComposeResult:
        yield Input(
            placeholder="Optional pytest arguments, e.g. tests/test_cli.py",
            id="args",
        )
        yield Input(
            placeholder="Enter exact test specification digest to approve...",
            id="digest",
        )
        with Horizontal(classes="action-row"):
            btn_run = Button("Run tests", id="btn-run", classes="btn-secondary")
            btn_run.disabled = True
            yield Button("▶ Preview command", id="btn-preview", classes="btn-primary")
            yield Button("Create spec", id="btn-create", classes="btn-secondary")
            yield btn_run
            yield Button("Approve digest", id="btn-approve", classes="btn-secondary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.spec = None
        self.approved = False

    @on(Button.Pressed)
    def run_test(self, event: Button.Pressed) -> None:
        try:
            if event.button.id == "btn-create":
                args = [x for x in self.query_one("#args", Input).value.split(" ") if x]
                self.spec = make_test_spec(self.app.workspace, arguments=args)
                self.approved = False
                self.query_one("#btn-run", Button).disabled = True
                spec_short = self.spec.digest[:8]
                self.query_one("#spec-status", Static).update(
                    "[#9CA3AF]SPEC      [/#9CA3AF] "
                    f"[bold #E5E7EB]{spec_short}[/bold #E5E7EB]"
                )
                self.show_result(
                    f"Specification Created:\n• Digest: {self.spec.digest}\n"
                    f"• Runner: pytest\n• Timeout: {self.spec.timeout_seconds}s"
                )
                self.app.emit_session_event("test specification created", kind="test")
            elif event.button.id == "btn-preview":
                if not self.spec:
                    raise ValueError("Create a test specification first.")
                cmd = f"pytest {' '.join(self.spec.arguments)}"
                self.show_result(
                    f"Exact Command: {cmd}\nDigest: {self.spec.digest}\n"
                    "Notice: Pytest executes repository code."
                )
                self.app.emit_session_event("test command previewed", kind="test")
            elif event.button.id == "btn-approve":
                if (
                    not self.spec
                    or self.query_one("#digest", Input).value.strip()
                    != self.spec.digest
                ):
                    raise ValueError("Exact specification digest is required.")
                self.approved = True
                self.query_one("#btn-run", Button).disabled = False
                self.query_one("#test-appr-status", Static).update(
                    "[#9CA3AF]APPROVAL  [/#9CA3AF] "
                    "[bold #89B4FA]Approved[/bold #89B4FA]"
                )
                self.show_result(
                    "Exact test digest approved. Press 'Run tests' to execute."
                )
                self.app.emit_session_event(
                    "test execution approved", self.spec.digest[:8], "test"
                )
            elif event.button.id == "btn-run":
                if not self.spec or not self.approved:
                    raise ValueError("Execution blocked: exact approval required.")
                approval = approve_test(self.spec, self.app.workspace)
                result = execute_test(self.spec, approval, self.app.workspace)
                proof = verify_execution(
                    None, self.app.test_evidence(result, self.spec), self.app.workspace
                )
                self.approved = False
                self.query_one("#btn-run", Button).disabled = True
                self.query_one("#test-appr-status", Static).update(
                    "[#9CA3AF]APPROVAL  [/#9CA3AF] "
                    "[bold #E5E7EB]Executed[/bold #E5E7EB]"
                )
                out = (result.stdout or result.stderr)[:1500]
                self.show_result(
                    f"Status: {result.status} (exit {result.exit_code})\n"
                    f"Duration: {result.duration_seconds}s\n"
                    f"Proof Status: {proof.overall_status}\n\n{out}",
                    kind="test",
                    title="TEST RESULTS",
                )
                self.app.emit_session_event("tests executed", result.status, "test")
        except Exception as error:
            self.show_result(f"Test error: {error}", kind="error")
            self.app.emit_session_event("test execution failed", kind="test")


class VerifyScreen(FeatureScreen):
    feature_name = "Verify"
    feature_title = "Verify Execution"
    feature_description = (
        "Run independent ProofEngine structural evidence verification."
    )
    pipeline_current = "verify"
    empty_output_text = (
        "No verification performed yet. Structural verification checks hashes."
    )

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("ENGINE", "ProofEngine (structural)"),
            ("WORKSPACE", self.app.workspace.name or str(self.app.workspace)),
            ("EVIDENCE", "Audit records & hashes"),
        ]

    def compose_action_area(self) -> ComposeResult:
        with Horizontal(classes="action-row"):
            yield Button("▶ Verify execution", id="btn-verify", classes="btn-primary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    @on(Button.Pressed, "#btn-verify")
    def run_verify(self) -> None:
        try:
            report = analyze_repository(self.app.workspace)
            proof = verify_execution(None, report, self.app.workspace)
            checks = "\n".join(f"  • {c.check_id}: {c.status}" for c in proof.checks)
            self.show_result(
                f"ProofEngine Status: {proof.overall_status}\n\nChecks:\n{checks}",
                kind="evidence",
                title="STRUCTURAL EVIDENCE VERIFICATION",
            )
            self.app.emit_session_event(
                "verification finished", proof.overall_status, "verify"
            )
        except Exception as error:
            self.show_result(f"Verification error: {error}", kind="error")
            self.app.emit_session_event("verification failed", kind="verify")


class HistoryScreen(FeatureScreen):
    feature_name = "History"
    feature_title = "Execution History"
    feature_description = "Browse sanitized AgentBlackBox execution audit records."
    pipeline_current = None
    empty_output_text = "No recorded executions are available."

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("STORAGE", "Local-only AgentBlackBox"),
            ("POLICY", "Encrypted · Sanitized"),
        ]

    def compose_action_area(self) -> ComposeResult:
        with Horizontal(classes="action-row"):
            yield Button("▶ Load history", id="btn-load", classes="btn-primary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    @on(Button.Pressed, "#btn-load")
    def run_history(self) -> None:
        try:
            records = history(LocalStorage(), limit=15)
            rows = "\n".join(
                f"  • {r.execution_id[:12]}.. [{r.status}] {r.capability_identifier}"
                for r in records
            )
            self.show_result(
                f"Recent Executions ({len(records)}):\n\n{rows or 'None found'}",
                kind="history",
                title="AUDIT HISTORY",
            )
        except Exception as error:
            self.show_result(f"History error: {error}", kind="error")


class ReplayScreen(FeatureScreen):
    feature_name = "Replay"
    feature_title = "Historical Replay"
    feature_description = (
        "Inspect chronological events of past executions in read-only mode."
    )
    pipeline_current = None
    empty_output_text = "Historical replay only. No capability will be executed."

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("AUDIT", "AgentBlackBox chronological trace"),
            ("SAFETY", "Read-only · No re-execution"),
        ]

    def compose_action_area(self) -> ComposeResult:
        yield Input(placeholder="Execution ID...", id="record-id")
        with Horizontal(classes="action-row"):
            yield Button("▶ Replay events", id="btn-replay", classes="btn-primary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    @on(Button.Pressed, "#btn-replay")
    def run_replay(self) -> None:
        rec_id = self.query_one("#record-id", Input).value.strip()
        if not rec_id:
            self.show_result("Enter an execution ID.", kind="error")
            self.app.emit_session_event("replay failed", kind="replay")
            return
        try:
            rec = replay(LocalStorage().load(rec_id))
            events = "\n".join(
                f"  • {e.sequence}. {e.event_type} at {e.timestamp.isoformat()}"
                for e in rec.events
            )
            self.show_result(
                f"Historical Replay for '{rec.execution_id}':\n\n{events}",
                kind="history",
                title="HISTORICAL REPLAY",
            )
            self.app.emit_session_event(
                "replay opened", rec.execution_id[:12], "replay"
            )
        except Exception as error:
            self.show_result(f"Replay error: {error}", kind="error")
            self.app.emit_session_event("replay failed", rec_id[:12], "replay")


class AIChatScreen(FeatureScreen):
    feature_name = "AI"
    feature_title = "Local AI Chat"
    feature_description = "Dedicated conversation with installed offline Ollama models."
    pipeline_current = None
    empty_output_text = "Select an installed local model to begin. No messages yet."

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("ENDPOINT", "127.0.0.1:11434 (Loopback Only)"),
            ("PROVIDER", "Ollama (local-first)"),
            ("FALLBACK", "Disabled · Zero cloud calls"),
        ]

    def compose_action_area(self) -> ComposeResult:
        yield Input(placeholder="Type a message to local Ollama...", id="prompt")
        with Horizontal(classes="action-row"):
            yield Button("▶ Send message", id="btn-send", classes="btn-primary")
            yield Button("Check models", id="btn-check", classes="btn-secondary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.models = []

    @on(Button.Pressed)
    def run_chat(self, event: Button.Pressed) -> None:
        try:
            srv = LocalAIService(load_settings())
            if event.button.id == "btn-check":
                self.models = srv.models()
                m_list = ", ".join(m.identifier for m in self.models)
                self.show_result(
                    f"Installed Models ({len(self.models)}):\n{m_list or 'None'}"
                )
                self.app.emit_session_event(
                    "AI check",
                    f"connected ({self.models[0].identifier})"
                    if self.models
                    else "unavailable",
                    "ai",
                )
            elif event.button.id == "btn-send":
                if not self.models:
                    self.models = srv.models()
                if not self.models:
                    raise ValueError("No installed local Ollama models found.")
                p = self.query_one("#prompt", Input).value.strip()
                if not p:
                    return
                resp = srv.ask(p, self.models[0].identifier)
                model_name = self.models[0].identifier
                self.show_result(
                    f"[bold #89B4FA]{model_name}:[/bold #89B4FA]\n\n{resp.response}"
                )
        except Exception as error:
            self.show_result(f"Local AI unavailable: {error}", kind="error")
            self.app.emit_session_event("AI check", "unavailable", "ai")


class SettingsScreen(FeatureScreen):
    feature_name = "Settings"
    feature_title = "Settings"
    feature_description = "Inspect active local-first policies and security boundaries."
    pipeline_current = None
    empty_output_text = "Configuration details."

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        cfg = load_settings()
        return [
            ("POLICY", "Local-first ENABLED"),
            ("CLOUD", "DISABLED"),
            ("SHELL", "ENABLED" if cfg.shell_command_execution_enabled else "DISABLED"),
            ("NETWORK", "ENABLED" if cfg.network_enabled else "DISABLED"),
        ]

    def compose_action_area(self) -> ComposeResult:
        with Horizontal(classes="action-row"):
            yield Button("▶ Reload settings", id="btn-reload", classes="btn-primary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    def on_mount(self) -> None:
        super().on_mount()
        self.load_settings_display()

    @on(Button.Pressed, "#btn-reload")
    def run_reload(self) -> None:
        self.load_settings_display()
        self.app.emit_session_event("settings reloaded", kind="settings")

    def load_settings_display(self) -> None:
        cfg = load_settings()
        cmd_exec = "ENABLED" if cfg.shell_command_execution_enabled else "DISABLED"
        info = (
            f"[bold #89B4FA]SECURITY[/bold #89B4FA]\n"
            f"Local-First Policy:             ENABLED\n"
            f"Cloud Providers:                DISABLED\n"
            f"Shell Command Execution:        {cmd_exec}\n"
            f"Network Access:                 {cfg.network_enabled}\n"
            f"Telemetry Enabled:              {cfg.telemetry_enabled}\n\n"
            f"[bold #89B4FA]LOCAL AI[/bold #89B4FA]\n"
            f"Ollama Endpoint:                {cfg.ollama_endpoint}\n\n"
            f"[bold #89B4FA]INTERFACE[/bold #89B4FA]\n"
            f"Theme:                          Graphite Command Center\n"
            f"Branding:                       Box-drawing Wordmark\n"
            f"Workspace:                      {self.app.workspace}"
        )
        self.show_result(info)


class HelpScreen(FeatureScreen):
    feature_name = "Help"
    feature_title = "Help & Command Reference"
    feature_description = (
        "Command reference, global keybindings, and safety boundaries."
    )
    pipeline_current = None
    empty_output_text = "Command reference and keybindings."

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("APP", "ZEROAGENT X"),
            ("VERSION", f"v{__version__}"),
            ("MODE", "Local-first · Proof-driven"),
            ("COMMANDS", f"{len(SLASH_COMMAND_REGISTRY)} registered"),
            ("Working directory", str(self.app.cwd_display)),
        ]

    def compose_action_area(self) -> ComposeResult:
        with Horizontal(classes="action-row"):
            yield Button("▶ Open palette", id="btn-palette", classes="btn-primary")
            yield Static("[#9CA3AF]esc home[/#9CA3AF]", classes="esc-hint")

    def on_mount(self) -> None:
        super().on_mount()
        cmds = "\n".join(
            f"  [bold #89B4FA]{cmd:<12}[/bold #89B4FA] [#E5E7EB]{feat}[/#E5E7EB]"
            for cmd, feat in SLASH_COMMAND_REGISTRY
        )
        keys = (
            "  [bold #89B4FA]tab[/bold #89B4FA]           "
            "[#E5E7EB]Cycle focus forward[/#E5E7EB]\n"
            "  [bold #89B4FA]shift+tab[/bold #89B4FA]     "
            "[#E5E7EB]Cycle focus backward[/#E5E7EB]\n"
            "  [bold #89B4FA]enter[/bold #89B4FA]         "
            "[#E5E7EB]Execute or activate focused button[/#E5E7EB]\n"
            "  [bold #89B4FA]/[/bold #89B4FA]             "
            "[#E5E7EB]Open Command Palette[/#E5E7EB]\n"
            "  [bold #89B4FA]esc[/bold #89B4FA]           "
            "[#E5E7EB]Return home / cancel[/#E5E7EB]\n"
            "  [bold #89B4FA]ctrl+c / q[/bold #89B4FA]    "
            "[#E5E7EB]Exit cleanly[/#E5E7EB]"
        )
        content = (
            f"[bold #89B4FA]Slash Commands[/bold #89B4FA]\n{cmds}\n\n"
            f"[bold #89B4FA]Global Keybindings[/bold #89B4FA]\n{keys}"
        )
        self.show_result(content)

    @on(Button.Pressed, "#btn-palette")
    def run_palette(self) -> None:
        self.action_palette()


class PipelineScreen(FeatureWorkbench):
    """Explicit controller for existing guarded PipelineEngine only."""

    feature_name = "Pipeline"
    feature_title = "Controlled Pipeline"
    feature_description = (
        "Explicit run, exact artifact approval, guarded local execution."
    )
    empty_output_text = "Runtime OFF. Enter task then choose Run Pipeline."

    def compose_info_rows(self) -> list[tuple[str, ...]]:
        return [
            ("RUNTIME", "OFF", "pipeline-runtime"),
            ("AWAITING", "None", "pipeline-awaiting"),
            ("WORKSPACE", self.app.workspace.name or str(self.app.workspace)),
        ]

    def compose_action_area(self) -> ComposeResult:
        yield Input(
            "",
            placeholder="Describe work for deterministic planning...",
            id="pipeline-task",
        )
        yield Input(
            "",
            placeholder="Patch proposal JSON path (required after planning)",
            id="pipeline-proposal",
        )
        yield Input(
            "", placeholder="Exact current artifact digest", id="pipeline-digest"
        )
        yield Input(
            "",
            placeholder="Optional allowlisted pytest arguments",
            id="pipeline-test-args",
        )
        with Horizontal(classes="action-row pipeline-actions"):
            yield Button("Start Pipeline", id="btn-pipeline-run", classes="btn-primary")
            yield Button(
                "Stop Pipeline", id="btn-pipeline-stop", classes="btn-secondary"
            )
            yield Button(
                "Load Edit Proposal",
                id="btn-pipeline-proposal",
                classes="btn-secondary",
            )
            yield Button(
                "Approve Edit", id="btn-pipeline-approve-edit", classes="btn-secondary"
            )
            yield Button(
                "Apply Approved Edit", id="btn-pipeline-apply", classes="btn-secondary"
            )
        with Horizontal(classes="action-row pipeline-actions"):
            yield Button(
                "Create Test Spec", id="btn-pipeline-test-spec", classes="btn-secondary"
            )
            yield Button(
                "Approve Test", id="btn-pipeline-approve-test", classes="btn-secondary"
            )
            yield Button(
                "Run Approved Test", id="btn-pipeline-test", classes="btn-secondary"
            )

    def on_mount(self) -> None:
        super().on_mount()
        self.refresh_pipeline()

    def refresh_pipeline(self) -> None:
        engine = self.app.pipeline_engine
        run = engine.active_run
        state = engine.state.value
        report = engine.last_report
        state_help = {
            "OFF": "Pipeline is not running.",
            "PREPARING": "Preparing requested workflow.",
            "RUNNING": "Executing current approved stage.",
            "AWAITING_APPROVAL": "Review current proposed action before continuing.",
            "CANCELLING": (
                "Cancellation requested. Waiting for active operation to finish safely."
            ),
            "COMPLETED": "Pipeline execution completed.",
            "FAILED": "Pipeline stopped because an operation failed.",
            "CANCELLED": "Pipeline stopped after cancellation.",
        }
        runtime = (
            f"Runtime: {state} — "
            f"{state_help.get(state, 'Pipeline status unavailable.')}"
        )
        if report:
            runtime += f"  Last run: {report.run.state.value}"
        self.query_one("#pipeline-runtime", Static).update(runtime)
        awaiting = run.awaiting if run else "None"
        awaiting_help = {
            "EDIT_PROPOSAL": "Load proposal JSON, then inspect exact diff.",
            "EDIT_APPROVAL": (
                "Enter current proposal digest to approve. "
                "Approval does not apply files."
            ),
            "APPLY_EDIT": (
                "Approval granted. Apply Approved Edit changes workspace files."
            ),
            "TEST_SPECIFICATION": "Create controlled allowlisted test specification.",
            "TEST_APPROVAL": (
                "Enter current test digest to approve. Approval does not run tests."
            ),
            "RUN_TEST": (
                "Approval granted. Run Approved Test starts allowed test runner."
            ),
            "None": "No action is awaiting approval.",
        }
        self.query_one("#pipeline-awaiting", Static).update(
            f"Awaiting: {awaiting} — "
            f"{awaiting_help.get(awaiting, 'Follow current Pipeline stage.')}"
        )
        active = run is not None
        buttons = {
            "#btn-pipeline-run": active,
            "#btn-pipeline-proposal": awaiting != "EDIT_PROPOSAL",
            "#btn-pipeline-approve-edit": awaiting != "EDIT_APPROVAL",
            "#btn-pipeline-apply": awaiting != "APPLY_EDIT"
            or bool(engine.active_operation),
            "#btn-pipeline-test-spec": awaiting != "TEST_SPECIFICATION",
            "#btn-pipeline-approve-test": awaiting != "TEST_APPROVAL",
            "#btn-pipeline-test": awaiting != "RUN_TEST"
            or bool(engine.active_operation),
            "#btn-pipeline-stop": not active or state == PipelineState.CANCELLING.value,
        }
        for selector, disabled in buttons.items():
            self.query_one(selector, Button).disabled = disabled

    def _report_text(self) -> str:
        engine = self.app.pipeline_engine
        report = engine.last_report
        if not report:
            return "No retained Pipeline report."
        limitation = report.limitation or (
            "Structural checks do not prove semantic correctness."
        )
        stages = "\n".join(
            f"• {stage.name}: {stage.outcome} — {stage.detail}"
            for stage in report.run.stages
        )
        return (
            f"Run: {report.run.run_id[:12]}\nTask: {report.run.task_summary}\n"
            f"Terminal: {report.run.state.value}\nApply: {report.apply_status}\n"
            f"Test: {report.test_status}\nStructural proof: {report.proof_status}\n"
            f"Cancellation: {report.cancellation_status}\n\n"
            f"Stages:\n{stages or 'Not available'}\n\n"
            f"{limitation}"
        )

    @on(Button.Pressed)
    async def run_pipeline_action(self, event: Button.Pressed) -> None:
        engine = self.app.pipeline_engine
        workspace = self.app.workspace
        try:
            match event.button.id:
                case "btn-pipeline-run":
                    task = self.query_one("#pipeline-task", Input).value.strip()
                    if not task:
                        raise PipelineError("Pipeline task is required")
                    await engine.start_async(task, workspace)
                case "btn-pipeline-proposal":
                    proposal = load_proposal(
                        Path(self.query_one("#pipeline-proposal", Input).value.strip())
                    )
                    diff = engine.submit_proposal(proposal, workspace)
                    self.show_result(
                        f"Workspace: {workspace}\nProposal: {proposal.proposal_id}\n"
                        f"Digest: {proposal.digest}\n\n{diff}",
                        kind="diff",
                        title="CURRENT EDIT PROPOSAL",
                    )
                case "btn-pipeline-approve-edit":
                    engine.approve_edit(
                        self.query_one("#pipeline-digest", Input).value.strip(),
                        workspace,
                    )
                case "btn-pipeline-apply":
                    self.show_result(
                        "Applying reviewed edit. Stop waits for Safe Edit settlement."
                    )
                    self.app.run_worker(
                        self._execute_apply(engine, workspace), exclusive=True
                    )
                    return
                case "btn-pipeline-test-spec":
                    args = [
                        arg
                        for arg in self.query_one(
                            "#pipeline-test-args", Input
                        ).value.split()
                        if arg
                    ]
                    spec = make_test_spec(workspace, arguments=args)
                    engine.submit_test_spec(spec, workspace)
                    self.show_result(
                        f"Workspace: {workspace}\n"
                        f"Specification: {spec.specification_id}\n"
                        f"Digest: {spec.digest}\nRunner: {spec.runner}\n"
                        f"Arguments: {' '.join(spec.arguments) or '(none)'}\n"
                        f"Timeout: {spec.timeout_seconds}s",
                        title="CURRENT TEST SPECIFICATION",
                    )
                case "btn-pipeline-approve-test":
                    engine.approve_test(
                        self.query_one("#pipeline-digest", Input).value.strip(),
                        workspace,
                    )
                case "btn-pipeline-test":
                    self.show_result(
                        "Running reviewed allowlisted tests. "
                        "Stop waits for runner settlement."
                    )
                    self.app.run_worker(
                        self._execute_test(engine, workspace), exclusive=True
                    )
                    return
                case "btn-pipeline-stop":
                    # cancel_async changes backend state before waiting for owned work.
                    # Run it separately so Textual can paint CANCELLING immediately.
                    self.app.run_worker(
                        self.app.stop_pipeline(
                            "Cancellation requested from Pipeline screen"
                        ),
                    )
                    await asyncio.sleep(0)
                    self.refresh_pipeline()
                    return
        except (OSError, ValueError, PipelineError) as error:
            self.show_result(f"Pipeline action blocked: {error}", kind="error")
        except Exception:
            if event.button.id == "btn-pipeline-apply":
                self.show_result(
                    "Apply failed.\n\nSome files may already have changed.\n"
                    "Automatic rollback is not guaranteed.\n"
                    "Review workspace and available recovery information "
                    "before retrying.",
                    kind="error",
                    title="APPLY FAILURE",
                )
                return
            self.show_result(
                "Pipeline operation failed. "
                "Review retained report and recovery information.",
                kind="error",
            )
        finally:
            self.refresh_pipeline()

    async def _execute_apply(self, engine: PipelineEngine, workspace: Path) -> None:
        try:
            await engine.execute_approved_edit_async(
                workspace, Path.home() / ".zeroagent" / "recovery"
            )
        except Exception:
            self.show_result(
                "Apply failed.\n\nSome files may already have changed.\n"
                "Automatic rollback is not guaranteed.\n"
                "Review workspace and available recovery information "
                "before retrying.",
                kind="error",
                title="APPLY FAILURE",
            )
        finally:
            self.refresh_pipeline()

    async def _execute_test(self, engine: PipelineEngine, workspace: Path) -> None:
        try:
            await engine.execute_approved_test_async(workspace)
        except Exception:
            self.show_result(
                "Pipeline test failed. Review retained report.", kind="error"
            )
        finally:
            self.refresh_pipeline()

    async def action_back(self) -> None:
        self.app.open_feature("home")


class CommandPalette(Screen):
    BINDINGS: ClassVar = [("escape", "dismiss", "Close")]

    COMMANDS = (
        ("00  Agent Workspace", "agent"),
        ("01  Analyze Repository", "analyze"),
        ("02  Ask About Repository", "context"),
        ("03  Safe Code Editing", "edit"),
        ("04  Run Controlled Tests", "test"),
        ("05  Verify Execution", "verify"),
        ("06  Execution History", "history"),
        ("07  Historical Replay", "replay"),
        ("08  Local AI Chat", "ai"),
        ("09  Settings", "settings"),
        ("10  Help & Commands", "help"),
        ("11  Controlled Pipeline", "pipeline"),
    )

    def compose(self) -> ComposeResult:
        with Container(id="palette-box"):
            yield Static("COMMAND PALETTE", classes="page-title")
            yield Static(
                "Select a capability. Arbitrary shell commands are blocked.",
                classes="page-subtitle",
            )
            yield OptionList(
                *[Option(title, id=target) for title, target in self.COMMANDS],
                id="palette-list",
            )

    @on(OptionList.OptionSelected, "#palette-list")
    def run_command(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id))

    def action_dismiss(self) -> None:
        self.dismiss(None)


class ZeroAgentApp(App):
    """Textual app provides alternate-screen, layout, focus, and screen lifecycle."""

    CSS = """
    * {
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 0;
        scrollbar-color: #343A45;
        scrollbar-color-hover: #9CA3AF;
        scrollbar-color-active: #89B4FA;
        scrollbar-background: #111318;
        scrollbar-background-hover: #111318;
        scrollbar-background-active: #111318;
    }
    Screen {
        background: #111318;
        color: #E5E7EB;
        align: center top;
    }
    SignatureBrandHeader {
        dock: top; height: 1; width: 100%; background: #111318;
        align-horizontal: center;
    }
    #header-bar { height: 1; width: 90%; max-width: 90; padding: 0 1; }
    #header-wordmark { width: 1fr; color: #89B4FA; text-style: bold; }
    #header-version { width: auto; text-align: right; color: #9CA3AF; }
    .screen-content {
        width: 100%; height: 1fr; background: transparent; border: none; padding: 0;
    }
    .content-frame-row { width: 100%; height: 1fr; }
    #home-scroll {
        align: center middle; width: 100%; height: 1fr; background: #111318;
        border: none;
    }
    DotField {
        height: 3;
        width: 100%;
        text-align: center;
    }
    ProofPipeline {
        height: 1;
        width: 100%;
        text-align: center;
        margin: 1 0;
    }
    #home-scroll.state-b {
        align: center top;
    }
    #home-inner {
        max-width: 80; width: 100%; height: auto; background: transparent;
        border: none; padding: 0;
    }
    #state-a-wordmark {
        text-align: center; color: #89B4FA; width: 100%;
        height: auto; margin-bottom: 0;
    }
    #state-a-cwd {
        dock: top; height: 1; width: 100%; padding: 0 2;
        color: #9CA3AF; text-align: right;
    }
    #state-a-tagline {
        text-align: center; color: #E5E7EB; width: 100%; height: auto;
    }
    #state-a-subtitle {
        text-align: center; color: #9CA3AF; width: 100%; height: auto;
        margin-bottom: 1;
    }
    #state-b-header {
        display: none; width: 100%; height: 1; margin: 0; padding: 0 2;
    }
    #state-b-brand {
        width: 1fr; color: #89B4FA; text-style: bold;
    }
    #state-b-version {
        width: auto; text-align: right; color: #9CA3AF;
    }
    #state-b-rule { display: none; }
    #home-workbench-body { width: 100%; height: 1fr; }
    #home-side-panel { display: none; }
    #planning-task {
        background: #22262D; color: #E5E7EB; border: none; border-left: thick #343A45;
        width: 100%; height: 3; padding: 1 2; margin: 0;
    }
    #planning-task:focus {
        border: none; border-left: thick #89B4FA;
    }
    #planning-hint {
        text-align: center; color: #9CA3AF; height: 1; margin-bottom: 1; width: 100%;
    }
    #home-hint-line {
        text-align: center; color: #9CA3AF; height: 1; margin-bottom: 1; width: 100%;
    }
    CommandChipsGrid {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        background: transparent;
        border: none;
        padding: 0;
    }
    .command-chip-row {
        width: 100%;
        height: 1;
        margin-bottom: 1;
        background: transparent;
        border: none;
        padding: 0;
    }
    .command-chip {
        width: 1fr;
        height: 1;
        margin-right: 1;
        background: #1B1E24;
        text-align: center;
        color: #E5E7EB;
        border: none;
    }
    .command-chip.last-chip { margin-right: 0; }
    .command-chip:hover {
        background: #22262D;
    }
    #plan-result {
        display: none; width: 100%; height: 1fr; margin-bottom: 1; color: #E5E7EB;
        background: transparent; border: none; text-align: left;
    }
    #state-b-actions {
        display: none; text-align: center; color: #9CA3AF; height: 1; margin-bottom: 1;
        width: 100%;
    }
    #state-b-commands {
        display: none; text-align: center; color: #9CA3AF; height: 1; margin-bottom: 1;
        width: 100%;
    }
    #home-status {
        text-align: center; color: #9CA3AF; height: 1; margin-top: 1; width: 100%;
    }

    /* Never put box border on widget with background unlike parent; use left bar. */
    HomeScreen.state-b #home-chips { display: none; }
    HomeScreen.state-b #state-a-wordmark { display: none; }
    HomeScreen.state-b #state-a-tagline { display: none; }
    HomeScreen.state-b #state-a-subtitle { display: none; }
    HomeScreen.state-b #home-hint-line { display: none; }

    HomeScreen.state-b #state-b-header { display: block; }
    HomeScreen.state-b #state-b-rule { display: block; }
    HomeScreen.state-b #home-workbench-body { layout: horizontal; }
    HomeScreen.state-b #home-scroll { width: 1fr; height: 1fr; }
    HomeScreen.state-b #home-inner { width: 100%; max-width: 100%; padding: 0 2; }
    HomeScreen.state-b #home-side-panel {
        display: block; width: 30; height: 1fr; padding: 0 2; margin: 0;
        border-left: solid #22262D;
    }
    HomeScreen.state-b #home-pipeline { display: none; }
    HomeScreen.state-b #home-side-panel #session-log { height: 1fr; }
    HomeScreen.state-b #home-side-panel ProofPipeline {
        height: 9; margin: 0; text-align: left;
    }
    HomeScreen.state-b #plan-result { display: block; }
    HomeScreen.state-b #state-b-actions { display: block; }
    HomeScreen.state-b #state-b-commands { display: none; }
    HomeScreen.state-b #planning-hint { text-align: left; margin: 0 0 1 0; }
    HomeScreen.state-b .output-label { margin: 0; }
    HomeScreen.state-b #home-dot-bottom { display: none; }
    HomeScreen.state-b #home-status { text-align: left; margin: 0; }
    HomeScreen.state-b.narrow-state-b #home-pipeline { display: block; }
    HomeScreen.state-b.narrow-state-b #home-side-panel { display: none; }

    VerticalScroll {
        height: 1fr;
        background: transparent;
        border: none;
        padding: 0;
    }
    .feature-top-bar { height: 1; width: 100%; padding: 0 2; }
    .feature-breadcrumb { width: 1fr; height: 1; }
    .feature-version {
        width: auto; text-align: right; color: #9CA3AF; height: 1;
    }
    .divider-rule { width: 100%; height: 1; color: #343A45; margin: 0; }
    .page-title {
        width: 100%; color: #E5E7EB; text-style: bold; height: auto; margin: 1 0 0 0;
    }
    .page-subtitle { width: 100%; color: #9CA3AF; margin-bottom: 1; height: auto; }
    #workbench-body { width: 100%; height: 1fr; layout: horizontal; }
    #feature-main { width: 1fr; height: 1fr; padding: 0 2; overflow-y: auto; }
    PipelineScreen #feature-main { overflow-y: hidden; }
    #side-panel {
        width: 30; height: 1fr; padding: 0 2; margin: 0;
        border-left: solid #22262D;
    }
    .side-title { height: 1; color: #9CA3AF; text-style: bold; }
    #session-log { width: 100%; height: 1fr; padding-left: 1; color: #E5E7EB; }
    #side-panel ProofPipeline { margin: 0; height: 9; text-align: left; }
    FeatureWorkbench.narrow-workbench #workbench-body { layout: vertical; }
    FeatureWorkbench.narrow-workbench #feature-main { width: 100%; height: 1fr; }
    FeatureWorkbench.narrow-workbench #side-panel {
        width: 100%; height: 2; padding: 0; margin: 0; border: none;
    }
    FeatureWorkbench.narrow-workbench #side-panel .side-title,
    FeatureWorkbench.narrow-workbench #side-panel #session-log { display: none; }
    FeatureWorkbench.narrow-workbench #side-panel ProofPipeline {
        width: 100%; text-align: center;
    }
    FeatureWorkbench.narrow-workbench #side-panel .side-rule { display: none; }
    FeatureWorkbench.narrow-workbench .page-subtitle,
    FeatureWorkbench.narrow-workbench #info-card { display: none; }
    FeatureWorkbench.narrow-workbench .page-title { margin-top: 0; }
    FeatureWorkbench.narrow-workbench .action-row { margin: 0; }
    FeatureWorkbench.narrow-workbench .output-label { margin-top: 0; }
    FeatureWorkbench #feature-bottom-dots { display: none; }
    FeatureWorkbench.narrow-workbench #feature-bottom-dots { display: block; }
    #info-card {
        background: #1B1E24; border: none; border-left: thick #343A45;
        padding: 1 2; margin: 1 0;
        height: auto; width: 100%;
    }
    .info-card-row { height: 1; color: #E5E7EB; }
    .action-row {
        height: 1; margin: 1 0; align-vertical: middle; width: 100%;
        background: transparent; border: none; padding: 0;
    }
    .esc-hint { height: 1; margin-left: 2; color: #9CA3AF; }
    Input {
        background: #22262D; color: #E5E7EB; border: none;
        border-left: thick #343A45;
        margin: 0; width: 100%; height: 3; padding: 1 2;
    }
    Input:focus { border: none; border-left: thick #89B4FA; }
    Input > .input--placeholder { color: #9CA3AF; }
    Button {
        height: 1; min-width: 12; padding: 0 2; border: none; margin-right: 1;
    }
    Button.btn-primary { background: #89B4FA; color: #111318; text-style: bold; }
    Button.btn-secondary { background: #22262D; color: #E5E7EB; text-style: none; }
    Button:focus, Button.-active {
        background: #343A45; color: #89B4FA; text-style: bold;
    }
    Button.btn-primary:focus {
        background: #B4D0FF; color: #111318; text-style: bold;
    }
    Button:hover { background: #343A45; color: #89B4FA; text-style: bold; }
    Button.btn-primary:hover { background: #B4D0FF; color: #111318; text-style: bold; }
    Button:disabled { background: #1B1E24; color: #6B7280; }
    .output-label { color: #9CA3AF; text-style: bold; margin-top: 1; height: 1; }
    #output-container {
        height: 1fr; margin-bottom: 1; width: 100%;
        background: transparent; border: none; padding: 0;
    }
    #result {
        width: 100%; height: auto; min-height: 4; background: transparent;
        border: none; padding: 0;
    }
    #plan-result-scroll {
        width: 100%; height: 1fr; background: transparent; border: none; padding: 0;
    }
    #plan-result-grid {
        layout: grid; grid-size: 2; grid-columns: 20 1fr; grid-rows: auto;
        grid-gutter: 1 1;
        width: 100%; height: auto; background: transparent; border: none; padding: 0;
    }
    .plan-label {
        width: 100%; height: auto; margin: 0; color: #9CA3AF; text-style: none;
    }
    .plan-value { width: 100%; height: auto; margin: 0; color: #E5E7EB; }
    ContextualFooter { dock: bottom; height: 1; padding: 0 1; background: #111318; }
    #footer-text { color: #9CA3AF; text-align: center; }
    #palette-box { width: 90%; max-width: 80; height: 75%; margin: 2 0;
        padding: 1; background: #1B1E24; border: solid #343A45; }
    #palette-list { height: 1fr; background: #22262D; }
    """

    BINDINGS: ClassVar = [
        ("q", "quit", "Quit"),
        ("/", "palette", "Command Palette"),
        ("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        workspace: Path | None = None,
        debug_mode: bool = False,
        enable_logo: bool = False,
    ) -> None:
        super().__init__()
        startup_cwd = Path.cwd().resolve()
        self.workspace = workspace or startup_cwd
        self.cwd_display = self._display_cwd(startup_cwd)
        self.debug_mode = debug_mode
        self.enable_logo = (
            False  # Graphics permanently disabled for Ubuntu terminal safety
        )
        self.home_plan: str | None = None
        self.session_events: deque[SessionEvent] = deque(maxlen=200)
        self.pipeline_engine = PipelineEngine(event_sink=self.emit_session_event)
        self._pipeline_stop_task = None
        self._shutdown_started = False
        self._pipeline_navigation_active = False
        self._agent_execution_active = False
        self._agent_settled = asyncio.Event()
        self._agent_settled.set()

    @staticmethod
    def _display_cwd(cwd: Path) -> str:
        try:
            return "~" + str(cwd).removeprefix(str(Path.home()))
        except ValueError:
            return str(cwd)

    def cwd_version_text(self, breadcrumb: str) -> Text:
        version = f"v{__version__}"
        available = max(1, self.size.width - 2 - len(breadcrumb) - len(version) - 8)
        path = self.cwd_display
        if len(path) > available:
            parts = path.split("/")
            compact = "/".join([parts[0] or "~", "…", *parts[-2:]])
            path = compact if len(compact) <= available else f"…/{parts[-1]}"
        return Text.assemble(
            (path, "#9CA3AF"), ("  ·  ", "#6B7280"), (version, "#9CA3AF")
        )

    def on_mount(self) -> None:
        self.emit_session_event("session started")
        self.push_screen(HomeScreen())

    def emit_session_event(
        self, title: str, detail: str = "", kind: str = "event"
    ) -> None:
        from datetime import datetime

        self.session_events.appendleft(
            SessionEvent(
                datetime.now().strftime("%H:%M"), kind, title[:40], detail[:200]
            )
        )
        for log in self.query(SessionLog):
            log.events = deque(self.session_events, maxlen=200)
            log.refresh_log()

    async def action_quit(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        await self.wait_agent_settlement()
        await self.shutdown_pipeline()
        self.exit()

    async def stop_pipeline(self, detail: str) -> None:
        """Single app-owned cancellation path; backend waits owned async work."""
        await self.pipeline_engine.cancel_async(detail)

    async def shutdown_pipeline(self) -> None:
        """App exit owns final settlement and blocks future starts."""
        await self.pipeline_engine.shutdown_async()

    def begin_agent_execution(self) -> None:
        self._agent_execution_active = True
        self._agent_settled.clear()

    def finish_agent_execution(self) -> None:
        self._agent_execution_active = False
        self._agent_settled.set()

    async def wait_agent_settlement(self) -> None:
        """Synchronous capability handlers cannot be safely force-cancelled."""
        await self._agent_settled.wait()

    def action_palette(self) -> None:
        self.push_screen(CommandPalette(), self._palette_result)

    def _palette_result(self, target: str | None) -> None:
        if target:
            self.open_feature(target)

    def open_feature(self, feature: str) -> None:
        mapping = {
            "home": HomeScreen,
            "agent": AgentScreen,
            "analyze": AnalyzeScreen,
            "context": ContextScreen,
            "edit": EditScreen,
            "test": TestScreen,
            "verify": VerifyScreen,
            "history": HistoryScreen,
            "replay": ReplayScreen,
            "ai": AIChatScreen,
            "settings": SettingsScreen,
            "help": HelpScreen,
            "pipeline": PipelineScreen,
        }
        screen = mapping.get(feature)
        if screen:
            if self._shutdown_started:
                return
            if isinstance(self.screen, PipelineScreen) and feature != "pipeline":
                if not self._pipeline_navigation_active:
                    self._pipeline_navigation_active = True
                    self.run_worker(self._leave_pipeline_then_open(screen))
                return
            self.push_screen(screen())

    async def _leave_pipeline_then_open(self, screen: type[Screen]) -> None:
        try:
            await self.stop_pipeline("Pipeline screen left")
            if not self._shutdown_started:
                self.push_screen(screen())
        finally:
            self._pipeline_navigation_active = False

    def handle_slash(self, cmd: str) -> None:
        name, _, argument = cmd.partition(" ")
        name = name.lower()
        if name == "/plan":
            task = argument.strip()
            if not task:
                self.home_plan = "Describe a task after /plan. No tools executed."
            else:
                try:
                    plan = validate_plan(create_plan(task, self.workspace))
                    self.home_plan = format_plan_result(plan)
                except Exception as error:
                    self.home_plan = f"Planning failed: {error}"
            while not isinstance(self.screen, HomeScreen):
                self.pop_screen()
            self.screen.set_state_b()
            return
        if name == "/?":
            self.action_palette()
            return
        if name == "/pipeline":
            action = argument.strip().lower()
            if action == "stop":
                self.run_worker(
                    self.stop_pipeline("Cancellation requested by /pipeline stop")
                )
                return
            self.open_feature("pipeline")
            if action == "run":
                self.emit_session_event(
                    "pipeline run blocked",
                    "Enter task then activate Run Pipeline",
                    "pipeline",
                )
            return
        if name == "/agent":
            self.open_feature("agent")
            return
        mapping = dict(SLASH_COMMAND_REGISTRY)
        mapping.update(
            {
                "/context": "context",
                "/model": "ai",
            }
        )
        target = mapping.get(name)
        if target:
            self.open_feature(target)
        else:
            self.action_palette()

    def patch_evidence(self, result):
        from zeroagent.editing import PatchEvidence

        return PatchEvidence(
            proposal_digest=result.proposal_digest,
            approval_bound=True,
            applied_paths=result.applied_paths,
            recovery_present=True,
            permissions_preserved=True,
        )

    def test_evidence(self, result, spec):
        return TestEvidence(
            specification_digest=spec.digest,
            approval_bound=True,
            runner_allowlisted=spec.runner in ALLOWLISTED_RUNNERS,
            execution_completed=result.status in ("PASSED", "FAILED"),
            exit_code_zero=result.exit_code == 0,
            output_integrity=not result.output_truncated,
        )
