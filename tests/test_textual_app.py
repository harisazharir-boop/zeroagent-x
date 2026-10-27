"""Textual full-screen Agent Workspace lifecycle, navigation, and safety tests."""

from __future__ import annotations

import asyncio
import hashlib
import threading
from pathlib import Path

import pytest
from textual.color import Color
from textual.widgets import Button, Input, Static

from tests.helpers import render_cells, render_lines
from zeroagent.editing import FileChange, make_proposal
from zeroagent.pipeline import PipelineError
from zeroagent.testing import TestExecutionResult, make_test_spec
from zeroagent.textual_app import (
    LARGE_GLYPHS,
    LARGE_WORDMARK_ROWS,
    SLASH_COMMAND_REGISTRY,
    WORDMARK_COLORS,
    WORDMARK_FALLBACK,
    WORDMARK_ROWS,
    AgentScreen,
    CommandChip,
    CommandChipsGrid,
    ContextScreen,
    ContextualFooter,
    DotField,
    FeatureScreen,
    FeatureWorkbench,
    HomeScreen,
    OutputPanel,
    PipelineScreen,
    PlanResultView,
    ProofPipeline,
    SessionEvent,
    SessionLog,
    WordmarkView,
    WorkflowStepper,
    ZeroAgentApp,
    detect_goal,
    outline_items,
    render_log_lines,
)


@pytest.mark.asyncio
async def test_agent_navigation_waits_for_active_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = threading.Event()

    def slow_run(task: str, workspace: Path):
        del task, workspace
        started.set()
        release.wait(timeout=2)
        from zeroagent.routing.router import run_task

        return run_task("Analyze this repository", tmp_path)

    monkeypatch.setattr("zeroagent.textual_app.run_task", slow_run)
    (tmp_path / "module.py").write_text("pass\n")
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        app.open_feature("agent")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AgentScreen)
        screen.query_one("#agent-task", Input).value = "Analyze this repository"
        await pilot.pause()
        screen.route_agent_task()
        execution = asyncio.create_task(screen.run_agent_task())
        await asyncio.wait_for(started.wait(), timeout=1)
        leaving = asyncio.create_task(screen.action_back())
        await pilot.pause()
        assert not leaving.done()
        release.set()
        await execution
        await leaving
        assert isinstance(app.screen, HomeScreen)
        assert app._agent_execution_active is False  # noqa: SLF001


@pytest.mark.asyncio
async def test_agent_quit_waits_for_active_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = threading.Event()

    def slow_run(task: str, workspace: Path):
        del task, workspace
        started.set()
        release.wait(timeout=2)
        from zeroagent.routing.router import run_task

        return run_task("Analyze this repository", tmp_path)

    monkeypatch.setattr("zeroagent.textual_app.run_task", slow_run)
    (tmp_path / "module.py").write_text("pass\n")
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        app.open_feature("agent")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AgentScreen)
        screen.query_one("#agent-task", Input).value = "Analyze this repository"
        await pilot.pause()
        screen.route_agent_task()
        execution = asyncio.create_task(screen.run_agent_task())
        await asyncio.wait_for(started.wait(), timeout=1)
        quitting = asyncio.create_task(app.action_quit())
        await pilot.pause()
        assert not quitting.done()
        release.set()
        await execution
        await quitting
        assert app._shutdown_started  # noqa: SLF001


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size", [(190, 45), (160, 45), (140, 40), (120, 35), (100, 30), (80, 24), (72, 24)]
)
async def test_agent_controls_remain_mounted_at_supported_sizes(
    size: tuple[int, int],
) -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=size) as pilot:
        app.open_feature("agent")
        await pilot.pause()
        for selector in ("#agent-task", "#btn-route", "#btn-run", "#btn-verify"):
            assert app.screen.query(selector)


@pytest.mark.asyncio
async def test_agent_routes_without_execution_and_runs_explicitly(
    tmp_path: Path,
) -> None:
    (tmp_path / "module.py").write_text("pass\n")
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        app.open_feature("agent")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AgentScreen)
        task = screen.query_one("#agent-task", Input)
        task.value = "Analyze this repository"
        await pilot.pause()
        screen.route_agent_task()
        assert screen.route is not None
        assert screen.execution is None
        assert screen.query_one("#btn-run", Button).disabled is False
        await screen.run_agent_task()
        assert screen.execution is not None
        screen.verify_agent_result()
        assert (
            "PROOF: VERIFIED" in screen.query_one("#result", OutputPanel).content_text
        )


@pytest.mark.asyncio
async def test_agent_task_change_invalidates_route(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test() as pilot:
        app.open_feature("agent")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, AgentScreen)
        task = screen.query_one("#agent-task", Input)
        task.value = "Analyze this repository"
        await pilot.pause()
        screen.route_agent_task()
        task.value = "Inspect dependencies"
        await pilot.pause()
        assert screen.route is None
        assert screen.query_one("#btn-run", Button).disabled is True


def test_render_log_lines_uses_fixed_timeline_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = [("09:05", "x" * 80), ("09:04", "older"), ("09:03", "last")]
    rows = render_log_lines(events, 24)
    assert all(len(row.plain) <= 24 for row in rows)
    assert all(row.plain[6] in "●│ " for row in rows)
    assert all(row.plain[:5] == row.plain[:5].rjust(5) for row in rows)
    # Two connector rows, one between each consecutive title-only event.
    assert sum("│" in row.plain for row in rows) == 2
    monkeypatch.setenv("ZEROAGENT_NO_DECOR", "1")
    assert all("│" not in row.plain for row in render_log_lines(events, 24))
    assert render_log_lines([], 24)[0].plain == "No activity yet."


def test_render_log_lines_wraps_words_and_preserves_timeline_columns() -> None:
    rows = render_log_lines(
        [
            SessionEvent(
                "09:05",
                "plan",
                "plan created",
                "one two three four five six seven eight",
            )
        ],
        20,
    )
    assert all(len(row.plain) <= 20 for row in rows)
    assert rows[0].plain[:5] == "09:05"
    assert all(row.plain[:5] == "     " for row in rows[1:])
    assert rows[0].plain[6] == "●"
    assert all(row.plain[6] == " " for row in rows[1:])
    assert "three" in "\n".join(row.plain for row in rows)
    assert render_log_lines([("09:05", "x" * 201)], 20)[-1].plain.endswith("…")


@pytest.mark.asyncio
async def test_render_helpers_preserve_requested_terminal_cell_geometry() -> None:
    app = ZeroAgentApp()
    lines = await render_lines(app, (190, 45))
    cells = await render_cells(ZeroAgentApp(), (190, 45))
    assert len(lines) == len(cells) == 45
    assert all(len(line) == 190 for line in lines)
    assert all(len(row) == 190 for row in cells)


def test_render_log_lines_detail_prefix_failing_reference() -> None:
    """Regression: historical detail prefix had five spaces before │."""
    rows = render_log_lines(
        [
            SessionEvent("13:32", "plan", "plan created", "one two three four"),
            SessionEvent("13:31", "event", "opened Analyze"),
        ],
        20,
    )
    assert rows[0].plain.index("●") == 6
    assert rows[1].plain.index("│") == 6
    assert rows[0].plain.index("plan") == rows[1].plain.index("one") == 8


def test_outline_items_extracts_bounded_plain_prompt_outline() -> None:
    prompt = """## First item
## Keep #012.3.25 and a*b
## First item
```python
## ignored
```
"""
    assert outline_items(prompt) == ["First item", "Keep #012.3.25 and a*b"]
    assert outline_items("1. One\n2) Two") == ["One", "Two"]
    assert outline_items("- One\n* Two") == ["One", "Two"]
    assert outline_items("plain prose") == []


def test_outline_items_prefers_heading_group_and_joins_list_continuations() -> None:
    prompt = "# Title\n## Subtitle\n" + "\n".join(
        f"## {index}. Section {index}" for index in range(8)
    )
    assert outline_items(prompt) == [f"Section {index}" for index in range(8)]
    wrapped = "1. First item continues\n   over another line\n2. Second\n3. Third"
    assert outline_items(wrapped)[0] == "First item continues over another line"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("# Title", []),
        ("# Title\n## Subtitle", []),
        ("- [ ] One\n- [x] Two", ["One", "Two"]),
        ("• not supported prose", []),
        ("```\n1. Ignore\n```\n1. Keep\n2. Also keep", ["Keep", "Also keep"]),
        ("1. Same\n2. Same\n3. Unique", ["Same", "Unique"]),
        ("1. café\n2. 東京", ["café", "東京"]),
        (
            "\n".join(f"{index}. Item {index}" for index in range(60)),
            [f"Item {index}" for index in range(50)],
        ),
    ],
)
def test_outline_items_boundary_fixture_matrix(
    source: str, expected: list[str]
) -> None:
    assert outline_items(source) == expected


def test_outline_items_caps_long_items_and_keeps_markdown_tokens() -> None:
    long_item = "1. Keep #012.3.32A " + "word " * 80
    result = outline_items(long_item + "\n2. Second")
    assert len(result[0]) <= 200
    assert result[0].endswith("…")
    assert "#012.3.32A" in result[0]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("   \n\t\n", []),
        ("## 1. One\n## 2. Two\n## 3. Three", ["One", "Two", "Three"]),
        ("### 1. One\n### 2. Two\n### 3. Three", ["One", "Two", "Three"]),
        (
            "- First item continues\n  over next line\n- Second\n  - Nested detail\n- Third",  # noqa: E501
            [
                "First item continues over next line",
                "Second - Nested detail",
                "Third",
            ],
        ),
        (
            "- [ ] First item continues\n  over next line\n- [x] Second\n- [ ] Third",
            ["First item continues over next line", "Second", "Third"],
        ),
        (
            "1. First\n2. Second\n\n- Longer first\n- Longer second\n- Longer third",
            ["Longer first", "Longer second", "Longer third"],
        ),
        (
            "# Title\n## Overview\n## 1. Inspect\n## 2. Improve\n"
            "## 3. Test\n## 4. Validate\n- Ignore list",
            ["Inspect", "Improve", "Test", "Validate"],
        ),
        (
            "1. Keep version #012.3.32A and a*b\n2. Next",
            ["Keep version #012.3.32A and a*b", "Next"],
        ),
    ],
)
def test_outline_items_complete_fixture_matrix(
    source: str, expected: list[str]
) -> None:
    assert outline_items(source) == expected


@pytest.mark.asyncio
async def test_plan_result_wraps_tasks_and_scrolls_without_footer_overlap() -> None:
    app = ZeroAgentApp()
    prompt = "\n".join(
        f"{index}. Improve rendering while preserving approved security boundaries "
        "across narrow terminal dimensions."
        for index in range(1, 51)
    )
    async with app.run_test(size=(100, 30)) as pilot:
        app.screen.create_plan(prompt, pasted=True, chars=len(prompt), lines=50)
        await pilot.pause()
        result = app.screen.query_one("#plan-result", PlanResultView)
        scroll = app.screen.query_one("#plan-result-scroll")
        footer = app.screen.query_one(ContextualFooter)
        assert scroll.max_scroll_y > 0
        assert result.region.bottom <= footer.region.y
        lines = [strip.text for strip in app.screen._compositor.render_strips()]  # noqa: SLF001
        todo_rows = [line for line in lines if "[ ]" in line]
        assert todo_rows
        assert all(len(line) <= 100 for line in lines)


@pytest.mark.asyncio
async def test_large_pasted_plan_is_bounded_and_nonexecuting() -> None:
    app = ZeroAgentApp()
    task = "1. " + ("safe planning text " * 600)
    async with app.run_test(size=(120, 35)) as pilot:
        app.screen.create_plan(task, pasted=True, chars=len(task), lines=1)
        await pilot.pause()
        result = app.screen.query_one("#plan-result", PlanResultView)
        assert len(task) >= 10_000
        assert "no file changes · no commands run" in result.content_text
        assert len(app.session_events[-1].detail) <= 200


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(160, 45), (120, 35), (100, 30), (80, 24)])
async def test_home_plan_compositor_baseline_at_supported_checkpoint_sizes(
    size: tuple[int, int],
) -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=size) as pilot:
        app.screen.create_plan("Improve rendered planning safety")
        await pilot.pause()
        lines = [strip.text for strip in app.screen._compositor.render_strips()]  # noqa: SLF001
        assert len(lines) == size[1]
        assert all(len(line) <= size[0] for line in lines)
        assert any("P L A N" in line for line in lines)
        assert any("Safety" in line for line in lines)


class _AskService:
    def __init__(
        self, response: str = "Local answer.", error: Exception | None = None
    ) -> None:
        self.response = response
        self.error = error
        self.calls = 0

    def models(self):
        from zeroagent.ai.models import InstalledModel

        return [InstalledModel(identifier="local-test", size_bytes=1)]

    def ask(self, prompt: str, model: str):
        from zeroagent.ai.models import GenerationResponse

        self.calls += 1
        if self.error:
            raise self.error
        return GenerationResponse(model=model, response=self.response)


@pytest.mark.asyncio
async def test_ask_renders_response_and_no_passive_resubmission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AskService("# Answer\n\nOne. café 東京\n\n" + "longtoken" * 700)
    monkeypatch.setattr("zeroagent.textual_app.LocalAIService", lambda _: service)
    app = ZeroAgentApp()
    async with app.run_test(size=(100, 30)) as pilot:
        app.open_feature("context")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ContextScreen)
        screen.query_one("#question", Input).value = "Explain ProofEngine"
        await pilot.click("#btn-ask")
        await pilot.pause()
        output = screen.query_one("#result", OutputPanel)
        scroll = screen.query_one("#output-container")
        assert "QUESTION" in output.content_text
        assert "ANSWER" in output.content_text
        assert "Local model · Response received" in output.content_text
        assert "東京" in output.content_text
        assert scroll.max_scroll_y > 0
        assert service.calls == 1
        app.open_feature("analyze")
        await pilot.press("escape")
        await pilot.pause()
        assert service.calls == 1


@pytest.mark.asyncio
async def test_ask_errors_stay_in_tui_without_provider_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _AskService(error=RuntimeError("token=private-provider-detail"))
    monkeypatch.setattr("zeroagent.textual_app.LocalAIService", lambda _: service)
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("context")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ContextScreen)
        await pilot.click("#btn-ask")
        await pilot.pause()
        output = screen.query_one("#result", OutputPanel)
        assert "Enter a question first." in output.content_text
        screen.query_one("#question", Input).value = "Question"
        screen.run_context(Button.Pressed(screen.query_one("#btn-ask", Button)))
        await pilot.pause()
        assert "No cloud fallback was attempted." in output.content_text
        assert "private-provider-detail" not in output.content_text
        lines = [strip.text for strip in app.screen._compositor.render_strips()]  # noqa: SLF001
        assert any("LOCAL AI UNAVAILABLE" in line for line in lines)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(160, 45), (120, 35), (100, 30), (80, 24)])
async def test_ask_empty_question_compositor_baseline_at_supported_checkpoint_sizes(
    size: tuple[int, int],
) -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=size) as pilot:
        app.open_feature("context")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ContextScreen)
        screen.run_context(Button.Pressed(screen.query_one("#btn-ask", Button)))
        await pilot.pause()
        output = screen.query_one("#result", OutputPanel)
        lines = [strip.text for strip in app.screen._compositor.render_strips()]  # noqa: SLF001
        assert "Enter a question first." in output.content_text
        assert len(lines) == size[1]
        assert all(len(line) <= size[0] for line in lines)


@pytest.mark.asyncio
async def test_rendered_session_log_alignment_survives_feature_transition() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(160, 45)) as pilot:
        app.emit_session_event(
            "plan created", "one two three four five six seven eight", "plan"
        )
        app.open_feature("context")
        await pilot.pause()
        lines = [strip.text for strip in app.screen._compositor.render_strips()]  # noqa: SLF001
        log = app.screen.query_one(SessionLog)
        x0, x1 = log.region.x, log.region.right
        log_rows = [line[x0:x1] for line in lines[log.region.y : log.region.bottom]]
        log_rows = [line for line in log_rows if "●" in line or "│" in line]
        glyph_columns = [max(line.rfind("●"), line.rfind("│")) for line in log_rows]
        assert len(log_rows) >= 3
        assert len(set(glyph_columns)) == 1
        for line in log_rows:
            marker = max(line.rfind("●"), line.rfind("│"))
            if "plan created" in line:
                assert line.index("plan created") == marker + 2
            elif "one two" in line:
                assert line.index("one two") == marker + 2


def test_detect_goal_skips_conditional_and_preserves_hash_tokens() -> None:
    goal = detect_goal("Context: Build around #012.3.25 safely.").goal
    assert goal == "Build around #012.3.25 safely."
    conditional = detect_goal("If it is not yet, implement X.").goal
    assert conditional != "If it is not yet, implement X."


@pytest.mark.asyncio
async def test_all_features_use_shared_workbench_and_session_log() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(160, 45)) as pilot:
        for _, feature in SLASH_COMMAND_REGISTRY:
            app.open_feature(feature)
            await pilot.pause()
            assert isinstance(app.screen, FeatureWorkbench)
            assert isinstance(app.screen, FeatureScreen)
            assert app.screen.query_one("#feature-main")
            assert app.screen.query_one("#side-panel")
            assert app.screen.query_one(SessionLog)
            assert app.screen.query_one("#output-container")


@pytest.mark.asyncio
async def test_textual_wordmark_rules_and_fallback() -> None:
    # 1. Compact and large programmatic wordmark tiers.
    assert len(WORDMARK_ROWS) == 5
    for row in WORDMARK_ROWS:
        assert len(row) == 61
        assert set(row) <= {"█", " "}
    assert len(LARGE_WORDMARK_ROWS) == 6
    assert all(len(row) == 88 for row in LARGE_WORDMARK_ROWS)
    for glyph in LARGE_GLYPHS.values():
        assert len({len(row) for row in glyph}) == 1
    assert WORDMARK_COLORS == (
        "#A6C8FF",
        "#9BBFFC",
        "#89B4FA",
        "#7AA5EC",
        "#6F9AE0",
    )
    assert WORDMARK_FALLBACK == "Z E R O A G E N T   X"

    app_wide = ZeroAgentApp()
    async with app_wide.run_test(size=(80, 35)):
        wm = app_wide.screen.query_one("#state-a-wordmark", WordmarkView)
        content = str(wm.renderable)
        assert WORDMARK_ROWS[0] in content
        assert wm.renderable.spans[0].style == WORDMARK_COLORS[0]

    app_narrow = ZeroAgentApp()
    async with app_narrow.run_test(size=(40, 24)):
        wm = app_narrow.screen.query_one("#state-a-wordmark", WordmarkView)
        content = str(wm.renderable)
        assert WORDMARK_FALLBACK in content


@pytest.mark.asyncio
async def test_textual_home_state_a_layout_and_plan_creation() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        assert isinstance(app.screen, HomeScreen)
        assert not app.screen.query("#main-menu")

        # 2. State A order and presence: DotField (top/bottom), composer, hint,
        # chips, ProofPipeline, status line
        dot_fields = list(app.screen.query(DotField))
        assert len(dot_fields) == 2
        assert dot_fields[0].position == "top"
        assert dot_fields[1].position == "bottom"

        wordmark = app.screen.query_one("#state-a-wordmark", WordmarkView)
        assert LARGE_WORDMARK_ROWS[0] in str(wordmark.renderable)

        # 3. Exactly one bordered widget on Home (the composer)
        assert not app.screen.query("#product-description")
        assert not app.screen.query("#home-description-card")
        assert not app.screen.query("#command-discovery-box")
        assert not app.screen.query("#home-status-card")
        assert not app.screen.query("#btn-create-plan")
        assert not app.screen.query(Button)

        bordered = [
            w
            for w in app.screen.query("*")
            if any(
                b[0] not in ("", "none")
                for b in (
                    w.styles.border_top,
                    w.styles.border_right,
                    w.styles.border_bottom,
                    w.styles.border_left,
                )
            )
        ]
        assert len(bordered) == 1
        assert bordered[0].id == "planning-task"

        # Chips grid and pipeline present
        assert app.screen.query_one(CommandChipsGrid)
        assert app.screen.query_one(ProofPipeline)

        # Truthful status line
        status_text = str(app.screen.query_one("#home-status", Static).renderable)
        assert "Proof Ready" in status_text
        assert "AI Not connected" in status_text

        # 5. Plan creation switches to State B
        task = app.screen.query_one("#planning-task", Input)
        task.value = "Improve error handling"
        await task.action_submit()
        await pilot.pause()

        assert app.screen.query_one("#home-scroll").has_class("state-b")
        assert app.screen.query_one("#state-b-header").display is True
        assert app.screen.query_one("#state-a-wordmark").display is False
        assert app.screen.query_one("#state-a-tagline").display is False
        assert app.screen.query_one("#state-a-subtitle").display is False

        plan_res = app.screen.query_one("#plan-result", PlanResultView)
        assert plan_res.display is True
        assert "PLAN CREATED" in plan_res.content_text
        assert "Improve error handling" in plan_res.content_text
        assert "Goal" in plan_res.content_text
        assert "Proposed Steps" in plan_res.content_text
        assert "Safety" in plan_res.content_text
        assert (
            "non-executing · no file changes · no commands run" in plan_res.content_text
        )


@pytest.mark.asyncio
async def test_textual_empty_enter_inline_hint_no_plan() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # 7. Empty Enter shows inline hint, creates no plan
        planning_input = app.screen.query_one("#planning-task", Input)
        planning_input.value = "   "
        await planning_input.action_submit()
        await pilot.pause()

        hint = str(app.screen.query_one("#planning-hint", Static).renderable)
        assert "Describe a task first." in hint
        assert app.home_plan is None
        assert not app.screen.query_one("#home-scroll").has_class("state-b")


@pytest.mark.asyncio
async def test_textual_home_plan_survives_navigation() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # 8. Plan survives navigation to a feature screen and back
        task = app.screen.query_one("#planning-task", Input)
        task.value = "Add a focused test"
        await task.action_submit()
        await pilot.pause()

        result = app.screen.query_one("#plan-result", PlanResultView).content_text
        app.open_feature("analyze")
        await pilot.press("escape")
        await pilot.pause()

        assert app.screen.query_one("#home-scroll").has_class("state-b")
        assert (
            result == app.screen.query_one("#plan-result", PlanResultView).content_text
        )


@pytest.mark.asyncio
async def test_textual_scrollbar_css_applied() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)):
        # 9. Scrollbar CSS values are applied (size 1, no bright-blue color)
        scroll = app.screen.query_one("#home-scroll")
        assert scroll.styles.scrollbar_size_vertical == 1
        assert scroll.styles.scrollbar_size_horizontal == 0
        assert scroll.styles.scrollbar_color == Color.parse("#343A45")
        assert scroll.styles.scrollbar_background == Color.parse("#111318")
        assert scroll.styles.scrollbar_color != Color.parse("#89B4FA")


@pytest.mark.asyncio
async def test_textual_slash_command_chips_rules() -> None:
    # 4. Chips: count and names equal SLASH_COMMAND_REGISTRY; click routes
    # like typed command; not in Tab order; 5/3/2 columns at widths >=60/<60/<40;
    # absent in State B and on feature screens.
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        chips = list(app.screen.query(CommandChip))
        assert len(chips) == len(SLASH_COMMAND_REGISTRY)
        chip_cmds = [c.command for c in chips]
        assert chip_cmds == [cmd for cmd, _ in SLASH_COMMAND_REGISTRY]

        # Not in tab order
        for c in chips:
            assert c.can_focus is False

        # Click routes like typed command
        analyze_chip = chips[0]
        await pilot.click(analyze_chip)
        await pilot.pause()
        assert app.screen.__class__.__name__ == "AnalyzeScreen"
        assert not app.screen.query(CommandChipsGrid)
        assert not app.screen.query(CommandChip)
        await pilot.press("escape")
        await pilot.pause()

        # Row-major five-column layout.
        grid = app.screen.query_one(CommandChipsGrid)
        assert grid.chip_columns() == 5

    app_mid = ZeroAgentApp()
    async with app_mid.run_test(size=(55, 30)):
        grid = app_mid.screen.query_one(CommandChipsGrid)
        assert grid.chip_columns() == 3

    app_narrow = ZeroAgentApp()
    async with app_narrow.run_test(size=(35, 20)):
        grid = app_narrow.screen.query_one(CommandChipsGrid)
        assert grid.chip_columns() == 2

    # Absent in State B
    app_b = ZeroAgentApp()
    async with app_b.run_test(size=(120, 35)) as pilot:
        task = app_b.screen.query_one("#planning-task", Input)
        task.value = "Create plan for state B check"
        await task.action_submit()
        await pilot.pause()
        assert app_b.screen.query_one("#home-chips").display is False


@pytest.mark.asyncio
async def test_textual_command_chips_are_row_major_with_spacing() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(100, 30)):
        rows = list(app.screen.query(".command-chip-row"))
        assert len(rows) == 3
        assert [chip.command for chip in rows[0].query(CommandChip)] == [
            "/analyze",
            "/ask",
            "/edit",
            "/test",
            "/verify",
        ]
        assert [chip.command for chip in rows[1].query(CommandChip)] == [
            "/history",
            "/replay",
            "/ai",
            "/settings",
            "/help",
        ]
        assert [chip.command for chip in rows[2].query(CommandChip)] == ["/pipeline"]
        for row in rows:
            assert len({chip.region.y for chip in row.query(CommandChip)}) == 1
        assert rows[1].region.y > rows[0].region.y + 1


@pytest.mark.asyncio
async def test_pipeline_screen_is_off_until_explicit_run(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        assert isinstance(app.screen, PipelineScreen)
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.active_task_count == 0
        assert "Pipeline is not running." in str(
            app.screen.query_one("#pipeline-runtime", Static).renderable
        )
        assert (
            app.screen.query_one("#btn-pipeline-run", Button).label.plain
            == "Start Pipeline"
        )
        await pilot.click("#btn-pipeline-run")
        await pilot.pause()
        assert app.pipeline_engine.state.value == "OFF"
        assert (
            "task is required"
            in app.screen.query_one("#result", OutputPanel).content_text
        )


@pytest.mark.asyncio
async def test_pipeline_approval_guidance_separates_approval_from_execution(
    tmp_path: Path,
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        await app.pipeline_engine.start_async("Approval guidance", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        app.screen.refresh_pipeline()
        awaiting = str(app.screen.query_one("#pipeline-awaiting", Static).renderable)
        assert "Load proposal JSON" in awaiting
        assert app.screen.query_one("#btn-pipeline-apply", Button).label.plain == (
            "Apply Approved Edit"
        )
        assert app.screen.query_one("#btn-pipeline-test", Button).label.plain == (
            "Run Approved Test"
        )
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_run_is_explicit_and_logs_lifecycle(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.handle_slash("/pipeline")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, PipelineScreen)
        screen.query_one("#pipeline-task", Input).value = "Review local workspace"
        await pilot.click("#btn-pipeline-run")
        await pilot.pause()
        assert app.pipeline_engine.state.value == "AWAITING_APPROVAL"
        assert app.pipeline_engine.active_run is not None
        assert app.pipeline_engine.active_run.awaiting == "EDIT_PROPOSAL"
        assert any(event.title == "pipeline started" for event in app.session_events)
        await app.stop_pipeline("test cleanup")
        screen.refresh_pipeline()
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.last_report is not None


async def _await_pipeline(engine, awaiting: str) -> None:
    for _ in range(20):
        if engine.active_run and engine.active_run.awaiting == awaiting:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"Pipeline did not await {awaiting}")


async def _wait_until(predicate, timeout: float = 5) -> None:
    async def wait() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout)


async def _approved_apply(app: ZeroAgentApp, workspace: Path):
    import zeroagent.pipeline.engine as pipeline_module

    (workspace / "app.txt").write_bytes(b"old\n")
    entered, release = threading.Event(), threading.Event()
    original = pipeline_module.apply

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    await app.pipeline_engine.start_async("Apply safely", workspace)
    await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
    proposal = make_proposal(
        workspace,
        [
            FileChange(
                path="app.txt",
                operation="modify",
                original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                new_content="updated\n",
                resulting_sha256=hashlib.sha256(b"updated\n").hexdigest(),
            )
        ],
        "Controlled change",
    )
    app.pipeline_engine.submit_proposal(proposal, workspace)
    app.pipeline_engine.approve_edit(proposal.digest, workspace)
    return entered, release, blocked


async def _approved_test(app: ZeroAgentApp, workspace: Path):
    (workspace / "app.txt").write_bytes(b"old\n")
    entered, release = threading.Event(), threading.Event()
    await app.pipeline_engine.start_async("Test safely", workspace)
    await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
    app.pipeline_engine.skip_edit("No edit requested")
    await _await_pipeline(app.pipeline_engine, "TEST_SPECIFICATION")
    spec = make_test_spec(workspace, arguments=["-q"])  # noqa: S106
    app.pipeline_engine.submit_test_spec(spec, workspace)
    app.pipeline_engine.approve_test(spec.digest, workspace)

    def blocked(*_args, **_kwargs):
        entered.set()
        assert release.wait(5)
        result = TestExecutionResult(
            execution_id="test-execution",
            specification_digest=spec.digest,
            runner="pytest",
            arguments=["-q"],
            status="PASSED",
            exit_code=0,
            duration_seconds=0.1,
            stdout="",
            stderr="",
        )
        return result

    return entered, release, blocked


@pytest.mark.asyncio
async def test_pipeline_ui_stop_during_apply_waits_for_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        entered, release, blocked = await _approved_apply(app, tmp_path)
        app.screen.refresh_pipeline()
        monkeypatch.setattr("zeroagent.pipeline.engine.apply", blocked)
        try:
            await app.screen.run_pipeline_action(
                Button.Pressed(app.screen.query_one("#btn-pipeline-apply", Button))
            )
            assert await asyncio.to_thread(entered.wait, 5)
            assert app.pipeline_engine.active_operation == "APPLY_EDIT"
            await pilot.click("#btn-pipeline-stop")
            await pilot.pause()
            screen = app.screen
            assert app.pipeline_engine.state.value == "CANCELLING"
            assert "CANCELLING" in str(
                screen.query_one("#pipeline-runtime", Static).renderable
            )
            assert app.pipeline_engine.active_task_count > 0
            assert app.pipeline_engine.last_report is None
        finally:
            release.set()
        for _ in range(20):
            if app.pipeline_engine.state.value == "OFF":
                break
            await pilot.pause()
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.last_report is not None
        assert app.pipeline_engine.active_task_count == 0


@pytest.mark.asyncio
async def test_pipeline_ui_apply_failure_warns_about_possible_partial_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        _, _, _ = await _approved_apply(app, tmp_path)
        app.screen.refresh_pipeline()

        def failed(*_args, **_kwargs):
            raise RuntimeError("write failed after earlier change")

        monkeypatch.setattr("zeroagent.pipeline.engine.apply", failed)
        await app.screen.run_pipeline_action(
            Button.Pressed(app.screen.query_one("#btn-pipeline-apply", Button))
        )
        await pilot.pause()
        output = app.screen.query_one("#result", OutputPanel).content_text
        assert "Some files may already have changed." in output
        assert "rollback is not guaranteed" in output
        assert app.pipeline_engine.last_report is not None
        assert app.pipeline_engine.last_report.test_status == "NOT_EXECUTED"


@pytest.mark.asyncio
async def test_pipeline_ui_stop_during_test_waits_for_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        entered, release, blocked = await _approved_test(app, tmp_path)
        app.screen.refresh_pipeline()
        monkeypatch.setattr("zeroagent.pipeline.engine.execute_test", blocked)
        try:
            await app.screen.run_pipeline_action(
                Button.Pressed(app.screen.query_one("#btn-pipeline-test", Button))
            )
            assert await asyncio.to_thread(entered.wait, 5)
            assert app.pipeline_engine.active_operation == "RUN_TEST"
            await pilot.click("#btn-pipeline-stop")
            await pilot.pause()
            assert app.pipeline_engine.state.value == "CANCELLING"
            assert "CANCELLING" in str(
                app.screen.query_one("#pipeline-runtime", Static).renderable
            )
            assert app.pipeline_engine.active_task_count > 0
            assert app.pipeline_engine.last_report is None
        finally:
            release.set()
        for _ in range(20):
            if app.pipeline_engine.state.value == "OFF":
                break
            await pilot.pause()
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.last_report is not None
        assert "VERIFY" not in [s.name for s in app.pipeline_engine.last_run.stages]
        assert app.pipeline_engine.active_task_count == 0


@pytest.mark.asyncio
async def test_pipeline_screen_leave_waits_for_active_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        entered, release, blocked = await _approved_apply(app, tmp_path)
        app.screen.refresh_pipeline()
        monkeypatch.setattr("zeroagent.pipeline.engine.apply", blocked)
        try:
            await app.screen.run_pipeline_action(
                Button.Pressed(app.screen.query_one("#btn-pipeline-apply", Button))
            )
            assert await asyncio.to_thread(entered.wait, 5)
            app.open_feature("home")
            await pilot.pause()
            assert app.pipeline_engine.state.value == "CANCELLING"
            assert isinstance(app.screen, PipelineScreen)
            assert app.pipeline_engine.active_operation == "APPLY_EDIT"
        finally:
            release.set()
        for _ in range(20):
            if isinstance(app.screen, HomeScreen):
                break
            await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.last_report is not None
        assert app.pipeline_engine.active_task_count == 0


@pytest.mark.asyncio
async def test_pipeline_screen_leave_waits_for_active_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        entered, release, blocked = await _approved_test(app, tmp_path)
        app.screen.refresh_pipeline()
        monkeypatch.setattr("zeroagent.pipeline.engine.execute_test", blocked)
        try:
            await app.screen.run_pipeline_action(
                Button.Pressed(app.screen.query_one("#btn-pipeline-test", Button))
            )
            assert await asyncio.to_thread(entered.wait, 5)
            app.open_feature("home")
            await pilot.pause()
            assert app.pipeline_engine.state.value == "CANCELLING"
            assert isinstance(app.screen, PipelineScreen)
            assert app.pipeline_engine.active_operation == "RUN_TEST"
        finally:
            release.set()
        for _ in range(20):
            if isinstance(app.screen, HomeScreen):
                break
            await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.last_report is not None
        assert "VERIFY" not in [s.name for s in app.pipeline_engine.last_run.stages]
        assert app.pipeline_engine.active_task_count == 0


@pytest.mark.asyncio
async def test_pipeline_concurrent_navigation_first_request_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        entered, release, blocked = await _approved_apply(app, tmp_path)
        app.screen.refresh_pipeline()
        monkeypatch.setattr("zeroagent.pipeline.engine.apply", blocked)
        try:
            await app.screen.run_pipeline_action(
                Button.Pressed(app.screen.query_one("#btn-pipeline-apply", Button))
            )
            assert await asyncio.to_thread(entered.wait, 5)
            app.open_feature("home")
            app.open_feature("settings")
            await pilot.pause()
            assert isinstance(app.screen, PipelineScreen)
            assert app.pipeline_engine.state.value == "CANCELLING"
        finally:
            release.set()
        for _ in range(20):
            if isinstance(app.screen, HomeScreen):
                break
            await pilot.pause()
        assert isinstance(app.screen, HomeScreen)
        assert app.pipeline_engine.active_task_count == 0
        assert [e.title for e in app.session_events].count("pipeline cancelled") == 1


@pytest.mark.asyncio
async def test_pipeline_ui_valid_edit_approval(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    proposal = make_proposal(
        tmp_path,
        [
            FileChange(
                path="app.txt",
                operation="modify",
                original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                new_content="updated\n",
                resulting_sha256=hashlib.sha256(b"updated\n").hexdigest(),
            )
        ],
        "Controlled change",
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(proposal.model_dump_json())
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#pipeline-task", Input).value = "Review change"
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-run", Button))
        )
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        screen.query_one("#pipeline-proposal", Input).value = str(proposal_path)
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-proposal", Button))
        )
        assert proposal.digest in screen.query_one("#result", OutputPanel).content_text
        screen.query_one("#pipeline-digest", Input).value = proposal.digest
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-approve-edit", Button))
        )
        assert app.pipeline_engine.active_run.awaiting == "APPLY_EDIT"
        assert app.pipeline_engine.application_result is None
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_ui_valid_test_approval(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("Test approval", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        app.pipeline_engine.skip_edit("No edit requested")
        await _await_pipeline(app.pipeline_engine, "TEST_SPECIFICATION")
        screen.refresh_pipeline()
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-test-spec", Button))
        )
        spec = app.pipeline_engine.test_spec
        assert spec is not None
        screen.query_one("#pipeline-digest", Input).value = spec.digest
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-approve-test", Button))
        )
        assert app.pipeline_engine.active_run.awaiting == "RUN_TEST"
        assert app.pipeline_engine.test_result is None
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_ui_rejects_stale_edit_artifact(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    proposal = make_proposal(
        tmp_path,
        [
            FileChange(
                path="app.txt",
                operation="modify",
                original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                new_content="updated\n",
                resulting_sha256=hashlib.sha256(b"updated\n").hexdigest(),
            )
        ],
        "Controlled change",
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(proposal.model_dump_json())
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("Stale edit", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        screen.query_one("#pipeline-proposal", Input).value = str(proposal_path)
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-proposal", Button))
        )
        screen.query_one("#pipeline-digest", Input).value = "stale"
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-approve-edit", Button))
        )
        assert app.pipeline_engine.active_run.awaiting == "EDIT_APPROVAL"
        assert app.pipeline_engine.patch_approval is None
        assert "does not match" in screen.query_one("#result", OutputPanel).content_text
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_ui_rejects_stale_test_specification(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("Stale test", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        app.pipeline_engine.skip_edit("No edit requested")
        await _await_pipeline(app.pipeline_engine, "TEST_SPECIFICATION")
        screen.refresh_pipeline()
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-test-spec", Button))
        )
        screen.query_one("#pipeline-digest", Input).value = "stale"
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-approve-test", Button))
        )
        assert app.pipeline_engine.active_run.awaiting == "TEST_APPROVAL"
        assert app.pipeline_engine.test_approval is None
        assert "does not match" in screen.query_one("#result", OutputPanel).content_text
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["apply", "test"])
async def test_pipeline_app_exit_waits_for_active_operation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    exited = asyncio.Event()
    monkeypatch.setattr(app, "exit", exited.set)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        if operation == "apply":
            entered, release, blocked = await _approved_apply(app, tmp_path)
            selector, target = "#btn-pipeline-apply", "apply"
        else:
            entered, release, blocked = await _approved_test(app, tmp_path)
            selector, target = "#btn-pipeline-test", "execute_test"
        app.screen.refresh_pipeline()
        monkeypatch.setattr(f"zeroagent.pipeline.engine.{target}", blocked)
        try:
            await app.screen.run_pipeline_action(
                Button.Pressed(app.screen.query_one(selector, Button))
            )
            assert await asyncio.to_thread(entered.wait, 5)
            quit_task = asyncio.create_task(app.action_quit())
            await asyncio.sleep(0)
            assert app.pipeline_engine.state.value == "CANCELLING"
            assert not exited.is_set()
            assert not quit_task.done()
        finally:
            release.set()
        await asyncio.wait_for(quit_task, 5)
        assert exited.is_set()
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.last_report is not None
        assert app.pipeline_engine.active_task_count == 0
        with pytest.raises(PipelineError, match="shut down"):
            app.pipeline_engine.start("restart", tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["apply", "test"])
async def test_pipeline_ui_duplicate_execution_executes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    calls = 0
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        if operation == "apply":
            entered, release, original = await _approved_apply(app, tmp_path)
            selector, target = "#btn-pipeline-apply", "apply"
        else:
            entered, release, original = await _approved_test(app, tmp_path)
            selector, target = "#btn-pipeline-test", "execute_test"

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        app.screen.refresh_pipeline()
        monkeypatch.setattr(f"zeroagent.pipeline.engine.{target}", counted)
        try:
            button = app.screen.query_one(selector, Button)
            await app.screen.run_pipeline_action(Button.Pressed(button))
            assert await asyncio.to_thread(entered.wait, 5)
            await app.screen.run_pipeline_action(Button.Pressed(button))
            assert calls == 1
            assert app.pipeline_engine.active_operation in {"APPLY_EDIT", "RUN_TEST"}
        finally:
            release.set()
        for _ in range(20):
            if app.pipeline_engine.active_operation is None:
                break
            await pilot.pause()
        assert calls == 1
        assert app.pipeline_engine.active_task_count == 0


@pytest.mark.asyncio
async def test_pipeline_quit_while_awaiting_approval(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    exited = asyncio.Event()
    app.exit = exited.set  # type: ignore[method-assign]
    async with app.run_test(size=(120, 35)):
        await app.pipeline_engine.start_async("Await approval", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        await app.action_quit()
        assert exited.is_set()
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.last_report is not None
        assert app.pipeline_engine.application_result is None
        assert app.pipeline_engine.test_result is None
        with pytest.raises(PipelineError, match="shut down"):
            app.pipeline_engine.start("restart", tmp_path)


@pytest.mark.asyncio
async def test_pipeline_duplicate_quit_is_idempotent(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    exits = 0

    def record_exit() -> None:
        nonlocal exits
        exits += 1

    app.exit = record_exit  # type: ignore[method-assign]
    async with app.run_test(size=(120, 35)):
        await asyncio.gather(app.action_quit(), app.action_quit())
        assert exits == 1
        assert app.pipeline_engine.state.value == "OFF"
        with pytest.raises(PipelineError, match="shut down"):
            app.pipeline_engine.start("restart", tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["q", "ctrl+c"])
async def test_home_keyboard_quit_uses_unified_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    exited = asyncio.Event()
    monkeypatch.setattr(app, "exit", exited.set)
    async with app.run_test(size=(120, 35)) as pilot:
        app.set_focus(None)
        await pilot.press(key)
        await _wait_until(exited.is_set)
        assert app._shutdown_started  # noqa: SLF001
        assert app.pipeline_engine.state.value == "OFF"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["q", "ctrl+c"])
async def test_feature_keyboard_quit_uses_unified_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    exited = asyncio.Event()
    monkeypatch.setattr(app, "exit", exited.set)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("analyze")
        await pilot.pause()
        assert isinstance(app.screen, FeatureWorkbench)
        app.set_focus(None)
        await pilot.press(key)
        await _wait_until(exited.is_set)
        assert app._shutdown_started  # noqa: SLF001
        assert app.pipeline_engine.state.value == "OFF"


@pytest.mark.asyncio
async def test_pipeline_stop_then_quit_waits_for_settlement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    exited = asyncio.Event()
    monkeypatch.setattr(app, "exit", exited.set)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        entered, release, blocked = await _approved_apply(app, tmp_path)
        monkeypatch.setattr("zeroagent.pipeline.engine.apply", blocked)
        screen = app.screen
        screen.refresh_pipeline()
        try:
            await screen.run_pipeline_action(
                Button.Pressed(screen.query_one("#btn-pipeline-apply", Button))
            )
            assert await asyncio.to_thread(entered.wait, 5)
            await screen.run_pipeline_action(
                Button.Pressed(screen.query_one("#btn-pipeline-stop", Button))
            )
            await _wait_until(lambda: app.pipeline_engine.state.value == "CANCELLING")
            app.set_focus(None)
            await pilot.press("q")
            await _wait_until(lambda: app._shutdown_started)  # noqa: SLF001
            assert app.pipeline_engine.active_operation == "APPLY_EDIT"
            assert not exited.is_set()
        finally:
            release.set()
        await _wait_until(exited.is_set)
        assert exited.is_set()
        assert app.pipeline_engine.state.value == "OFF"
        assert app.pipeline_engine.last_report is not None
        assert app.pipeline_engine.active_task_count == 0
        assert [event.title for event in app.session_events].count(
            "pipeline cancelled"
        ) == 1


@pytest.mark.asyncio
async def test_pipeline_navigation_then_quit_prioritizes_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    exited = asyncio.Event()
    monkeypatch.setattr(app, "exit", exited.set)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        entered, release, blocked = await _approved_apply(app, tmp_path)
        monkeypatch.setattr("zeroagent.pipeline.engine.apply", blocked)
        screen = app.screen
        screen.refresh_pipeline()
        try:
            await screen.run_pipeline_action(
                Button.Pressed(screen.query_one("#btn-pipeline-apply", Button))
            )
            assert await asyncio.to_thread(entered.wait, 5)
            app.open_feature("home")
            await _wait_until(lambda: app._pipeline_navigation_active)  # noqa: SLF001
            await _wait_until(lambda: app.pipeline_engine.state.value == "CANCELLING")
            app.set_focus(None)
            await pilot.press("q")
            await _wait_until(lambda: app._shutdown_started)  # noqa: SLF001
            assert isinstance(app.screen, PipelineScreen)
            assert not exited.is_set()
        finally:
            release.set()
        await _wait_until(exited.is_set)
        assert exited.is_set()
        assert not isinstance(app.screen, HomeScreen)
        assert app.pipeline_engine.active_task_count == 0
        assert [event.title for event in app.session_events].count(
            "pipeline cancelled"
        ) == 1


@pytest.mark.asyncio
async def test_pipeline_ui_rejects_workspace_mismatch(tmp_path: Path) -> None:
    workspace_b = tmp_path.parent / f"{tmp_path.name}-other"
    workspace_b.mkdir()
    (tmp_path / "app.txt").write_bytes(b"old\n")
    proposal = make_proposal(
        tmp_path,
        [
            FileChange(
                path="app.txt",
                operation="modify",
                original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                new_content="updated\n",
                resulting_sha256=hashlib.sha256(b"updated\n").hexdigest(),
            )
        ],
        "Controlled change",
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(proposal.model_dump_json())
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("Workspace binding", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        screen.query_one("#pipeline-proposal", Input).value = str(proposal_path)
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-proposal", Button))
        )
        app.workspace = workspace_b
        screen.query_one("#pipeline-digest", Input).value = proposal.digest
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-approve-edit", Button))
        )
        assert app.pipeline_engine.active_run.awaiting == "EDIT_APPROVAL"
        assert app.pipeline_engine.patch_approval is None
        assert "bound" in screen.query_one("#result", OutputPanel).content_text
        assert app.pipeline_engine.active_operation is None
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_ui_rejects_replaced_edit_artifact(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")

    def proposal_for(content: str):
        return make_proposal(
            tmp_path,
            [
                FileChange(
                    path="app.txt",
                    operation="modify",
                    original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                    new_content=content,
                    resulting_sha256=hashlib.sha256(content.encode()).hexdigest(),
                )
            ],
            content,
        )

    first, replacement = proposal_for("one\n"), proposal_for("two\n")
    first_path, replacement_path = (
        tmp_path / "first.json",
        tmp_path / "replacement.json",
    )
    first_path.write_text(first.model_dump_json())
    replacement_path.write_text(replacement.model_dump_json())
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("Replacement", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        screen.query_one("#pipeline-proposal", Input).value = str(first_path)
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-proposal", Button))
        )
        assert (
            app.pipeline_engine.proposal
            and app.pipeline_engine.proposal.proposal_id == first.proposal_id
        )
        screen.query_one("#pipeline-proposal", Input).value = str(replacement_path)
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-proposal", Button))
        )
        assert (
            app.pipeline_engine.proposal
            and app.pipeline_engine.proposal.proposal_id == first.proposal_id
        )
        assert app.pipeline_engine.active_run.awaiting == "EDIT_APPROVAL"
        assert (
            "awaiting a different action"
            in screen.query_one("#result", OutputPanel).content_text
        )
        assert app.pipeline_engine.active_operation is None
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_ui_rejects_replaced_test_specification(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("Replacement", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        app.pipeline_engine.skip_edit("No edit requested")
        await _await_pipeline(app.pipeline_engine, "TEST_SPECIFICATION")
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-test-spec", Button))
        )
        first = app.pipeline_engine.test_spec
        assert first is not None
        screen.query_one("#pipeline-test-args", Input).value = "-q -x"
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-test-spec", Button))
        )
        assert app.pipeline_engine.test_spec is first
        assert app.pipeline_engine.active_run.awaiting == "TEST_APPROVAL"
        assert (
            "awaiting a different action"
            in screen.query_one("#result", OutputPanel).content_text
        )
        assert app.pipeline_engine.active_operation is None
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_ui_stale_run_approval_cannot_authorize_new_run(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")

    def proposal_for(content: str):
        return make_proposal(
            tmp_path,
            [
                FileChange(
                    path="app.txt",
                    operation="modify",
                    original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                    new_content=content,
                    resulting_sha256=hashlib.sha256(content.encode()).hexdigest(),
                )
            ],
            content,
        )

    first, second = proposal_for("one\n"), proposal_for("two\n")
    first_path, second_path = tmp_path / "first.json", tmp_path / "second.json"
    first_path.write_text(first.model_dump_json())
    second_path.write_text(second.model_dump_json())
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("First run", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        screen.query_one("#pipeline-proposal", Input).value = str(first_path)
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-proposal", Button))
        )
        first_run_id = app.pipeline_engine.active_run.run_id
        await app.stop_pipeline("end first run")
        await app.pipeline_engine.start_async("Second run", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        screen.query_one("#pipeline-proposal", Input).value = str(second_path)
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-proposal", Button))
        )
        assert app.pipeline_engine.active_run.run_id != first_run_id
        screen.query_one("#pipeline-digest", Input).value = first.digest
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-approve-edit", Button))
        )
        assert app.pipeline_engine.patch_approval is None
        assert app.pipeline_engine.active_run.awaiting == "EDIT_APPROVAL"
        assert "does not match" in screen.query_one("#result", OutputPanel).content_text
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_ui_duplicate_edit_approval_is_safe(tmp_path: Path) -> None:
    (tmp_path / "app.txt").write_bytes(b"old\n")
    proposal = make_proposal(
        tmp_path,
        [
            FileChange(
                path="app.txt",
                operation="modify",
                original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                new_content="updated\n",
                resulting_sha256=hashlib.sha256(b"updated\n").hexdigest(),
            )
        ],
        "Controlled change",
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(proposal.model_dump_json())
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("Duplicate approval", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        screen.query_one("#pipeline-proposal", Input).value = str(proposal_path)
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-proposal", Button))
        )
        screen.query_one("#pipeline-digest", Input).value = proposal.digest
        button = screen.query_one("#btn-pipeline-approve-edit", Button)
        await screen.run_pipeline_action(Button.Pressed(button))
        approval = app.pipeline_engine.patch_approval
        await screen.run_pipeline_action(Button.Pressed(button))
        assert app.pipeline_engine.patch_approval is approval
        assert app.pipeline_engine.active_run.awaiting == "APPLY_EDIT"
        assert app.pipeline_engine.application_result is None
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
async def test_pipeline_ui_duplicate_test_approval_is_safe(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        screen = app.screen
        await app.pipeline_engine.start_async("Duplicate test approval", tmp_path)
        await _await_pipeline(app.pipeline_engine, "EDIT_PROPOSAL")
        app.pipeline_engine.skip_edit("No edit requested")
        await _await_pipeline(app.pipeline_engine, "TEST_SPECIFICATION")
        await screen.run_pipeline_action(
            Button.Pressed(screen.query_one("#btn-pipeline-test-spec", Button))
        )
        spec = app.pipeline_engine.test_spec
        assert spec is not None
        screen.query_one("#pipeline-digest", Input).value = spec.digest
        button = screen.query_one("#btn-pipeline-approve-test", Button)
        await screen.run_pipeline_action(Button.Pressed(button))
        approval = app.pipeline_engine.test_approval
        await screen.run_pipeline_action(Button.Pressed(button))
        assert app.pipeline_engine.test_approval is approval
        assert app.pipeline_engine.active_run.awaiting == "RUN_TEST"
        assert app.pipeline_engine.test_result is None
        await app.stop_pipeline("test cleanup")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size", [(190, 45), (160, 45), (140, 40), (120, 35), (100, 30), (80, 24), (72, 24)]
)
async def test_pipeline_compositor_preserves_run_controls(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=size) as pilot:
        app.open_feature("pipeline")
        await pilot.pause()
        assert isinstance(app.screen, PipelineScreen)
        assert app.screen.query_one("#pipeline-task", Input).display
        assert app.screen.query_one("#btn-pipeline-run", Button).display
        lines = [strip.text for strip in app.screen._compositor.render_strips()]  # noqa: SLF001
        assert len(lines) == size[1]
        assert all(len(line) <= size[0] for line in lines)


@pytest.mark.asyncio
async def test_textual_home_focuses_composer_on_mount_and_resume() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        composer = app.screen.query_one("#planning-task", Input)
        assert app.focused is composer
        assert composer.styles.border_left[1] == Color.parse("#89B4FA")
        app.open_feature("analyze")
        await pilot.press("escape")
        await pilot.pause()
        assert app.focused is composer


@pytest.mark.asyncio
async def test_textual_state_b_keybindings_and_isolation() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        task = app.screen.query_one("#planning-task", Input)
        task.value = "Initial plan"
        await task.action_submit()
        await pilot.pause()
        assert app.screen.query_one("#home-scroll").has_class("state-b")

        # Esc on State B moves focus back to input
        app.set_focus(None)
        assert app.focused != task
        await pilot.press("escape")
        assert app.focused == task

        # When input is focused, typing 'n' types 'n' and does not reset plan
        await pilot.press("n")
        assert task.value.endswith("n")
        assert app.screen.query_one("#home-scroll").has_class("state-b")

        # When input is NOT focused, 'n' creates new plan (resets to State A)
        app.set_focus(None)
        assert app.focused != task
        await pilot.press("n")
        await pilot.pause()
        assert not app.screen.query_one("#home-scroll").has_class("state-b")
        assert app.screen.query_one("#state-a-wordmark").display is True
        assert task.value == ""


@pytest.mark.asyncio
async def test_textual_slash_commands_route_correctly() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        app.handle_slash("/analyze")
        assert app.screen.__class__.__name__ == "AnalyzeScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/ask")
        assert app.screen.__class__.__name__ == "ContextScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/edit")
        assert app.screen.__class__.__name__ == "EditScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/test")
        assert app.screen.__class__.__name__ == "TestScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/verify")
        assert app.screen.__class__.__name__ == "VerifyScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/history")
        assert app.screen.__class__.__name__ == "HistoryScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/replay")
        assert app.screen.__class__.__name__ == "ReplayScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/ai")
        assert app.screen.__class__.__name__ == "AIChatScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/settings")
        assert app.screen.__class__.__name__ == "SettingsScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)

        app.handle_slash("/help")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "HelpScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_textual_planning_input_is_home_only() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        planning_input = app.screen.query_one("#planning-task", Input)
        planning_input.value = "test prompt query"
        await planning_input.action_submit()
        await pilot.pause()
        assert (
            "test prompt query"
            in app.screen.query_one("#plan-result", PlanResultView).content_text
        )
        app.open_feature("analyze")
        assert not app.screen.query("#planning-task, #btn-create-plan, #plan-result")


@pytest.mark.asyncio
async def test_textual_slash_plan_returns_home_without_plan_screen() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)):
        app.open_feature("analyze")
        app.handle_slash("/plan Document local policy")
        assert isinstance(app.screen, HomeScreen)
        assert (
            "Document local policy"
            in app.screen.query_one("#plan-result", PlanResultView).content_text
        )
        assert "PlanScreen" not in {
            screen.__name__
            for screen in app.__class__.__dict__.values()
            if isinstance(screen, type)
        }


@pytest.mark.asyncio
async def test_textual_escape_returns_to_home() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("test")
        assert app.screen.__class__.__name__ == "TestScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_textual_ctrl_c_exits_cleanly() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running is False


@pytest.mark.asyncio
async def test_textual_command_palette_opens_and_dismisses() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        app.action_palette()
        await pilot.pause()
        assert app.screen.__class__.__name__ == "CommandPalette"
        palette_list = app.screen.query_one("#palette-list")
        prompts = [
            str(palette_list.get_option_at_index(i).prompt)
            for i in range(len(app.screen.COMMANDS))
        ]
        # Never contains arbitrary shell or bash commands
        assert not any(
            "bash" in p.lower() or "shell" in p.lower() or "rm" in p.lower()
            for p in prompts
        )
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_textual_all_ten_screens_navigate_cleanly() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        for _, feature in SLASH_COMMAND_REGISTRY:
            app.open_feature(feature)
            await pilot.pause()
            assert isinstance(app.screen, FeatureScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_textual_shared_decoration_widgets_rules() -> None:
    # 8. DotField and ProofPipeline exist on Home State A AND every feature screen;
    # absent in State B; both are the shared widget classes (assert types).
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        # Home State A
        assert len(app.screen.query(DotField)) == 2
        assert len(app.screen.query(ProofPipeline)) == 2

        # Every feature screen
        for _, feature in SLASH_COMMAND_REGISTRY:
            app.open_feature(feature)
            await pilot.pause()
            assert len(app.screen.query(DotField)) == 2
            assert len(app.screen.query(ProofPipeline)) == 1
            await pilot.press("escape")
            await pilot.pause()

        # State B keeps frame decoration.
        task = app.screen.query_one("#planning-task", Input)
        task.value = "Check State B decoration"
        await task.action_submit()
        await pilot.pause()
        assert app.screen.query_one("#home-side-pipeline").display is True
        assert app.screen.query_one("#home-dot-top", DotField).display is True
        assert app.screen.query_one("#home-dot-bottom", DotField).display is False


@pytest.mark.asyncio
async def test_textual_pipeline_highlights_location_only() -> None:
    # 9. /edit, /test, /verify highlight their own word; others highlight none;
    # highlight never changes from backend events.
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        for _, feature in SLASH_COMMAND_REGISTRY:
            app.open_feature(feature)
            await pilot.pause()
            pipeline = app.screen.query_one(ProofPipeline)
            rendered = str(pipeline.renderable)
            if feature in ("edit", "test", "verify"):
                assert pipeline.current == feature
                assert f"[bold #89B4FA]{feature}[/bold #89B4FA]" in rendered
            else:
                assert pipeline.current is None
                assert "[bold #89B4FA]edit[/bold #89B4FA]" not in rendered
                assert "[bold #89B4FA]test[/bold #89B4FA]" not in rendered
                assert "[bold #89B4FA]verify[/bold #89B4FA]" not in rendered
            await pilot.press("escape")
            await pilot.pause()


@pytest.mark.asyncio
async def test_textual_decoration_opt_out_and_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 10. ZEROAGENT_NO_DECOR=1 hides all decoration; height < 30 hides DotField;
    # width < 60 hides ProofPipeline; decoration widgets not focusable.
    monkeypatch.setenv("ZEROAGENT_NO_DECOR", "1")
    app_no_decor = ZeroAgentApp()
    async with app_no_decor.run_test(size=(120, 35)):
        for df in app_no_decor.screen.query(DotField):
            assert df.display is False
        assert app_no_decor.screen.query_one(ProofPipeline).display is False

    monkeypatch.delenv("ZEROAGENT_NO_DECOR", raising=False)
    # height < 30 hides DotField
    app_short = ZeroAgentApp()
    async with app_short.run_test(size=(120, 25)):
        for df in app_short.screen.query(DotField):
            assert df.display is False
        assert app_short.screen.query_one(ProofPipeline).display is True

    # width < 60 hides ProofPipeline
    app_narrow = ZeroAgentApp()
    async with app_narrow.run_test(size=(50, 35)):
        for df in app_narrow.screen.query(DotField):
            assert df.display is True
        assert app_narrow.screen.query_one(ProofPipeline).display is False

    # Decoration widgets are not focusable
    app_focus = ZeroAgentApp()
    async with app_focus.run_test(size=(120, 35)):
        for df in app_focus.screen.query(DotField):
            assert df.can_focus is False
        assert app_focus.screen.query_one(ProofPipeline).can_focus is False


@pytest.mark.asyncio
async def test_textual_feature_screens_shared_base_and_contracts() -> None:
    # 11. All derive from shared FeatureScreen base; breadcrumb top bar,
    # title, description, OUTPUT label, footer with `esc home`; no Home composer/chips.
    # 12. Exactly one primary button per screen; empty state plain text, not Panel.
    from rich.panel import Panel

    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        for _, feature in SLASH_COMMAND_REGISTRY:
            app.open_feature(feature)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, FeatureScreen)

            # Breadcrumb and version
            breadcrumb = str(screen.query_one(".feature-breadcrumb", Static).renderable)
            assert "ZEROAGENT X" in breadcrumb
            assert "›" in breadcrumb
            assert screen.feature_name in breadcrumb
            version = str(screen.query_one(".feature-version", Static).renderable)
            assert "v0.12.0.dev0" in version

            # Title and description
            assert screen.query_one(".page-title", Static)
            assert screen.query_one(".page-subtitle", Static)

            # Output label
            output_label = str(screen.query_one(".output-label", Static).renderable)
            assert "O U T P U T" in output_label

            # Footer with esc home
            footer = screen.query_one(ContextualFooter)
            footer_text = str(footer.query_one("#footer-text", Static).renderable)
            assert "esc" in footer_text
            assert "home" in footer_text
            assert "Back to Studio" not in footer_text

            # No Home composer / chips
            assert not screen.query("#planning-task")
            assert not screen.query(CommandChipsGrid)

            # Exactly one primary button
            primary_buttons = list(screen.query("Button.btn-primary"))
            assert len(primary_buttons) == 1

            # Empty state is plain text, not Panel
            output_panel = screen.query_one("#result", OutputPanel)
            assert not isinstance(output_panel.renderable, Panel)

            await pilot.press("escape")
            await pilot.pause()


@pytest.mark.asyncio
async def test_textual_feature_frame_matches_reference_geometry() -> None:
    for size in ((237, 45), (200, 50), (160, 45), (120, 35)):
        app = ZeroAgentApp()
        async with app.run_test(size=size) as pilot:
            for _, feature in SLASH_COMMAND_REGISTRY:
                app.open_feature(feature)
                await pilot.pause()
                main = app.screen.query_one("#feature-main")
                panel = app.screen.query_one("#side-panel")
                panel_width = min(max(size[0] // 5, 32), 44)
                assert main.region.x == 0
                assert main.region.width == size[0] - panel_width
                assert panel.region.x == size[0] - panel_width
                assert panel.region.width == panel_width
                pane_widths = {
                    app.screen.query_one("#info-card").region.width,
                    app.screen.query_one(".output-rule").region.width,
                    app.screen.query_one("#output-container").region.width,
                }
                assert pane_widths == {main.region.width - 4}
                assert app.screen.query_one(".feature-top-bar").region.width == size[0]
                assert app.screen.query_one(".feature-rule").region.width == size[0]
                await pilot.press("escape")
                await pilot.pause()


@pytest.mark.asyncio
async def test_textual_no_wrapper_surface_around_bordered_children() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        for _, feature in SLASH_COMMAND_REGISTRY:
            app.open_feature(feature)
            await pilot.pause()
            for widget in app.screen.query("*"):
                if not list(widget.children):
                    continue
                has_bordered_child = any(
                    any(
                        edge[0] not in ("", "none")
                        for edge in (
                            child.styles.border_top,
                            child.styles.border_right,
                            child.styles.border_bottom,
                            child.styles.border_left,
                        )
                    )
                    for child in widget.children
                )
                if has_bordered_child:
                    assert widget.styles.background.a == 0
                    if widget.id != "feature-main":
                        assert widget.styles.padding == (0, 0, 0, 0)
                    assert widget.styles.border_top[0] in ("", "none")
            await pilot.press("escape")
            await pilot.pause()


@pytest.mark.asyncio
async def test_textual_permission_primary_buttons_are_safe_previews() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        expected = {
            "context": "btn-preview",
            "edit": "btn-preview",
            "test": "btn-preview",
        }
        for feature, primary_id in expected.items():
            app.open_feature(feature)
            await pilot.pause()
            primary = app.screen.query_one("Button.btn-primary", Button)
            assert primary.id == primary_id
            await pilot.press("escape")
            await pilot.pause()


@pytest.mark.asyncio
async def test_textual_startup_with_kitty_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    monkeypatch.setenv("TERM", "xterm-kitty")
    app = ZeroAgentApp()
    async with app.run_test(size=(80, 24)) as pilot:
        assert isinstance(app.screen, HomeScreen)
        assert not app.screen.query("#main-menu")
        app.handle_slash("/analyze")
        assert app.screen.__class__.__name__ == "AnalyzeScreen"
        await pilot.press("escape")
        assert isinstance(app.screen, HomeScreen)


@pytest.mark.asyncio
async def test_textual_no_graphics_escape_sequences() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(80, 24)):
        # 12. No graphics escape sequences emitted
        assert isinstance(app.screen, HomeScreen)
        assert app.enable_logo is False
        assert not app.screen.query("#header-logo")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(160, 45), (120, 35), (100, 30), (80, 24)])
async def test_textual_single_column_responsive_layout(
    size: tuple[int, int],
) -> None:
    # 11. Responsive: 160x45, 120x35, 100x30, 80x24
    app = ZeroAgentApp()
    async with app.run_test(size=size) as pilot:
        assert isinstance(app.screen, HomeScreen)
        inner = app.screen.query_one("#home-inner")
        planning_input = app.screen.query_one("#planning-task")
        footer = app.screen.query_one(ContextualFooter)
        assert not app.screen.query("#main-menu")
        assert not app.screen.query("#nav-sidebar, #info-sidebar")
        assert inner.region.width <= 80
        assert planning_input.region.width <= 80
        assert footer.region.y == size[1] - 1

        # Test in State B as well
        planning_input.value = "Responsive plan test"
        await planning_input.action_submit()
        await pilot.pause()
        if size[0] >= 120 and size[1] >= 24:
            panel_width = min(max(size[0] // 5, 32), 44)
            assert inner.region.width == size[0] - panel_width
            assert planning_input.region.width == size[0] - panel_width - 4
        else:
            assert inner.region.width <= 100
            assert planning_input.region.width <= 100
        assert footer.region.y == size[1] - 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "size",
    [(190, 45), (160, 45), (140, 40), (120, 35), (100, 30), (80, 24), (72, 24)],
)
async def test_full_home_and_plan_compositor_matrix(size: tuple[int, int]) -> None:
    """Every checkpoint size keeps Home input, footer, and plan result in bounds."""
    app = ZeroAgentApp()
    async with app.run_test(size=size) as pilot:
        home = app.screen
        assert isinstance(home, HomeScreen)
        composer = home.query_one("#planning-task", Input)
        footer = home.query_one(ContextualFooter)
        assert composer.region.bottom <= footer.region.y
        assert footer.region.bottom == size[1]
        lines = [strip.text for strip in app.screen._compositor.render_strips()]  # noqa: SLF001
        assert len(lines) == size[1]
        assert all(len(line) <= size[0] for line in lines)

        composer.value = "Create responsive plan"
        await composer.action_submit()
        await pilot.pause()
        result = home.query_one("#plan-result", PlanResultView)
        assert result.region.bottom <= footer.region.y
        assert home.query_one("#plan-result-scroll").region.width > 0
        if size[0] < 120:
            assert home.query_one("#home-side-panel").display is False
        else:
            assert home.query_one(SessionLog).display is True


@pytest.mark.asyncio
async def test_resize_sequence_preserves_home_focus_and_plan_geometry() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(190, 45)) as pilot:
        home = app.screen
        assert isinstance(home, HomeScreen)
        composer = home.query_one("#planning-task", Input)
        composer.value = "Resize plan"
        await composer.action_submit()
        for size in ((120, 35), (80, 24), (140, 40)):
            await pilot.resize_terminal(*size)
            await pilot.pause()
            footer = home.query_one(ContextualFooter)
            result = home.query_one("#plan-result", PlanResultView)
            assert footer.region.bottom == size[1]
            assert result.region.bottom <= footer.region.y
            assert home.query_one("#planning-task", Input).region.width > 0
        await pilot.press("escape")
        assert app.focused is composer


@pytest.mark.asyncio
async def test_session_log_rendering_and_redraws_do_not_mutate_events() -> None:
    app = ZeroAgentApp()
    events = [
        (
            "plan created",
            "Improve terminal rendering across multiple dimensions.",
            "plan",
        ),
        ("analysis finished", "12 files", "analysis"),
        ("ask answered", "", "ask"),
        ("patch previewed", "", "edit"),
        ("test specification created", "", "test"),
        ("verification finished", "passed", "verify"),
        ("replay opened", "record-123", "replay"),
        ("AI check", "unavailable", "ai"),
        ("settings reloaded", "", "settings"),
    ]
    async with app.run_test(size=(160, 45)) as pilot:
        for title, detail, kind in events:
            app.emit_session_event(title, detail, kind)
        original = tuple(app.session_events)
        log = app.screen.query_one(SessionLog)
        log.refresh_log()
        await pilot.pause()
        for _ in range(2):
            _ = list(app.screen._compositor.render_strips())  # noqa: SLF001
        await pilot.resize_terminal(140, 40)
        await pilot.pause()
        assert tuple(app.session_events) == original
        assert tuple(log.events) == original
        rows = render_log_lines(list(log.events), log.content_size.width)
        marked = [row.plain for row in rows if "●" in row.plain or "│" in row.plain]
        assert marked
        assert all(row[6] in "●│ " for row in marked)
        baseline = render_log_lines(
            [
                SessionEvent(
                    "09:05", "plan", "plan created", "Improve terminal rendering"
                )
            ],
            40,
        )
        assert baseline[0].plain.index("plan created") == 8
        assert baseline[1].plain.index("Improve") == 8
        assert [event.title for event in app.session_events][: len(events)] == [
            title for title, _, _ in reversed(events)
        ]


@pytest.mark.asyncio
async def test_feature_navigation_only_adds_intended_event_not_redraw_events() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        initial = len(app.session_events)
        app.open_feature("analyze")
        await pilot.pause()
        assert len(app.session_events) == initial + 1
        opened = tuple(app.session_events)
        for _ in range(2):
            _ = list(app.screen._compositor.render_strips())  # noqa: SLF001
        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        assert tuple(app.session_events) == opened
        await pilot.press("escape")
        await pilot.pause()
        assert tuple(app.session_events) == opened


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(160, 45), (120, 35), (80, 24)])
async def test_feature_screen_compositor_contract_at_representative_sizes(
    size: tuple[int, int],
) -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=size) as pilot:
        for feature in (
            "analyze",
            "context",
            "edit",
            "test",
            "verify",
            "history",
            "replay",
            "settings",
        ):
            app.open_feature(feature)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, FeatureScreen)
            assert screen.query_one("#result", OutputPanel).region.width > 0
            footer = screen.query_one(ContextualFooter)
            assert footer.region.bottom == size[1]
            assert (
                screen.query_one("#output-container").region.bottom <= footer.region.y
            )
            lines = [strip.text for strip in screen._compositor.render_strips()]  # noqa: SLF001
            assert len(lines) == size[1]
            assert all(len(line) <= size[0] for line in lines)
            await pilot.press("escape")
            await pilot.pause()


@pytest.mark.asyncio
async def test_textual_footer_contains_minimal_navigation() -> None:
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        footer = app.screen.query_one(ContextualFooter)
        text_widget = footer.query_one("#footer-text", Static)
        rendered_a = str(text_widget.renderable)
        assert "commands" in rendered_a
        assert "create plan" in rendered_a
        assert "ctrl+c exit" in rendered_a

        task = app.screen.query_one("#planning-task", Input)
        task.value = "Switch to State B"
        await task.action_submit()
        await pilot.pause()
        rendered_b = str(text_widget.renderable)
        assert "commands" in rendered_b
        assert "new plan" in rendered_b
        assert "esc" in rendered_b
        assert "ctrl+c exit" in rendered_b


@pytest.mark.asyncio
async def test_textual_workflow_stepper() -> None:
    stepper = WorkflowStepper(["One", "Two", "Three"], current_index=1)
    app = ZeroAgentApp()
    async with app.run_test(size=(120, 35)) as pilot:
        await app.screen.mount(stepper)
        await pilot.pause()
        text = str(stepper.query_one(".workflow-stepper-text", Static).renderable)
        assert "✓ One" in text
        assert "(2) Two" in text
        assert "3 Three" in text


@pytest.mark.asyncio
async def test_textual_safe_edit_requires_approval(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_bytes(b"old\n")

    proposal = make_proposal(
        tmp_path,
        [
            FileChange(
                path="app.py",
                operation="modify",
                original_sha256=hashlib.sha256(b"old\n").hexdigest(),
                new_content="new\n",
                resulting_sha256=hashlib.sha256(b"new\n").hexdigest(),
            )
        ],
        "replace content",
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(proposal.model_dump_json())

    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("edit")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "EditScreen"

        # Initially Apply button is disabled
        btn_apply = app.screen.query_one("#btn-apply", Button)
        assert btn_apply.disabled is True

        # Load proposal
        input_widget = app.screen.query_one("#proposal-path", Input)
        input_widget.value = str(proposal_path)
        await pilot.click("#btn-load")

        # Preview changes without modifying
        await pilot.click("#btn-preview")
        assert target.read_text() == "old\n"

        # Apply still disabled before approval
        assert btn_apply.disabled is True

        # Enter exact approval digest and apply
        digest_input = app.screen.query_one("#digest", Input)
        digest_input.value = proposal.digest
        await pilot.click("#btn-approve")

        # Now apply is enabled
        assert btn_apply.disabled is False
        await pilot.click("#btn-apply")
        assert target.read_text() == "new\n"


@pytest.mark.asyncio
async def test_textual_controlled_test_requires_approval(tmp_path: Path) -> None:
    test_file = tmp_path / "test_ok.py"
    test_file.write_text("def test_ok(): assert 1 == 1\n")

    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        app.open_feature("test")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "TestScreen"

        # Initially Run button is disabled
        btn_run = app.screen.query_one("#btn-run", Button)
        assert btn_run.disabled is True

        # Set runner args
        args_input = app.screen.query_one("#args", Input)
        args_input.value = str(test_file)

        # Stage test specification
        await pilot.click("#btn-create")
        assert btn_run.disabled is True

        # Enter matching approval digest
        digest_input = app.screen.query_one("#digest", Input)
        digest_input.value = app.screen.spec.digest
        await pilot.click("#btn-approve")

        # Now Run is enabled
        assert btn_run.disabled is False
        await pilot.click("#btn-run")
        await pilot.pause()
        panel = app.screen.query_one("#result", OutputPanel)
        assert "Status: PASSED" in panel.content_text


@pytest.mark.asyncio
async def test_textual_handled_ai_and_replay_errors(tmp_path: Path) -> None:
    app = ZeroAgentApp(workspace=tmp_path)
    async with app.run_test(size=(120, 35)) as pilot:
        # Replay with empty execution ID
        app.open_feature("replay")
        await pilot.pause()
        btn = app.screen.query_one("#btn-replay", Button)
        await pilot.click(btn)
        await pilot.pause()
        panel = app.screen.query_one("#result", OutputPanel)
        assert "Enter an execution ID" in panel.content_text

        # Replay with invalid/non-existent execution ID
        input_box = app.screen.query_one("#record-id", Input)
        input_box.focus()
        await pilot.press("n", "o", "n", "e")
        await pilot.click(btn)
        await pilot.pause()
        panel = app.screen.query_one("#result", OutputPanel)
        assert "Replay error" in panel.content_text

        # AI chat with empty prompt or unreachable endpoint
        await pilot.press("escape")
        app.open_feature("ai")
        await pilot.pause()
        await pilot.click("#btn-check")
        panel = app.screen.query_one("#result", OutputPanel)
        assert isinstance(panel, OutputPanel)
        assert panel.content_text != ""

        # Verify screen handled execution without crash
        await pilot.press("escape")
        app.open_feature("verify")
        await pilot.pause()
        await pilot.click("#btn-verify")
        panel = app.screen.query_one("#result", OutputPanel)
        assert (
            "ProofEngine Status" in panel.content_text
            or "Verification error" in panel.content_text
        )
