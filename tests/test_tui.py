"""Tests for Neon Minimal TUI state, rendering, and real local integration."""

from io import StringIO
from pathlib import Path

from rich.console import Console

from zeroagent.tui import MENU, NeonMinimalTui


def _tui(
    workspace: Path | None = None, width: int = 100
) -> tuple[NeonMinimalTui, StringIO]:
    stream = StringIO()
    console = Console(file=stream, force_terminal=False, width=width)
    return NeonMinimalTui(console=console, workspace=workspace), stream


def test_main_menu_rendering_contains_brand_and_actions() -> None:
    interface, stream = _tui()
    interface.render()
    output = stream.getvalue()
    assert "AGENT X" in output
    assert "Don't Just Run AI. Prove It Works." in output
    assert all(item in output for item in MENU)


def test_keyboard_navigation_numeric_and_invalid_input() -> None:
    interface, _ = _tui()
    interface.handle("down")
    assert interface.state.selected == 1
    interface.handle("\x1b[A")
    assert interface.state.selected == 0
    interface.handle("up")
    assert interface.state.selected == len(MENU) - 1
    interface.handle("8")
    assert interface.state.screen == "settings"
    interface.handle("nonsense")
    assert "Invalid input" in interface.state.message


def test_escape_returns_home_and_slash_task_argument(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("pass\n")
    interface, _ = _tui(tmp_path)
    interface.handle("/run Analyze this repository")
    assert interface.state.screen == "run"
    interface.handle("esc")
    assert interface.state.screen == "home"
    interface.handle("/analyze " + str(tmp_path))
    assert interface.state.screen == "analysis"
    interface.handle("/context auth")
    assert interface.state.screen == "context"


def test_slash_commands_and_screen_transitions(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("pass\n")
    interface, _ = _tui(tmp_path)
    interface.handle("/analyze")
    assert interface.state.screen == "analysis"
    assert interface.state.last_report is not None
    interface.handle("/verify")
    assert interface.state.screen == "verify"
    assert "Proof status: VERIFIED" in interface.state.message
    interface.handle("/history")
    assert interface.state.screen == "history"
    interface.handle("/replay")
    assert interface.state.screen == "replay"
    interface.handle("/help")
    assert interface.state.screen == "help"


def test_narrow_render_and_unavailable_ai(monkeypatch) -> None:
    interface, stream = _tui(width=40)
    interface.render()
    assert "ZEROAGENT X" in stream.getvalue()

    class Service:
        def doctor(self):
            from zeroagent.ai.models import ProviderInfo

            return ProviderInfo(endpoint="http://127.0.0.1:11434", reachable=False)

    monkeypatch.setattr("zeroagent.tui.LocalAIService", lambda settings: Service())
    interface.handle("/model")
    assert interface.state.screen == "ai"
    assert "unavailable" in interface.state.message


def test_tui_quit_and_noninteractive_guard(monkeypatch) -> None:
    interface, _ = _tui()
    assert interface.handle("/exit") is False

    class Stream:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("zeroagent.tui.sys.stdin", Stream())
    try:
        interface.run_interactive()
    except RuntimeError as error:
        assert "interactive terminal" in str(error)
    else:
        raise AssertionError("Expected noninteractive TUI rejection")


def test_tui_ai_repeated_single_turn_and_safe_response(monkeypatch) -> None:
    interface, stream = _tui()

    class Service:
        def doctor(self):
            from zeroagent.ai.models import ProviderInfo

            return ProviderInfo(endpoint="http://127.0.0.1:11434", reachable=True)

        def models(self):
            from zeroagent.ai.models import InstalledModel

            return [
                InstalledModel(identifier="tiny"),
                InstalledModel(identifier="other"),
            ]

        def ask(self, prompt: str, model: str):
            from zeroagent.ai.models import GenerationResponse

            return GenerationResponse(model=model, response=f"answer\x1b[31m:{prompt}")

    monkeypatch.setattr("zeroagent.tui.LocalAIService", lambda settings: Service())
    interface.handle("/model")
    interface.handle("first prompt")
    interface.handle("/model")
    interface.handle("second prompt")
    interface.render()
    assert interface.state.ai_response == "answer\x1b[31m:second prompt"
    assert "answer?[31m:second prompt" in stream.getvalue()
    assert "Prior messages are not sent" in stream.getvalue()


def test_tui_history_inspection_and_replay_never_runs_handler(monkeypatch) -> None:
    interface, _ = _tui()
    calls = []

    class Event:
        sequence = 1
        event_type = "capability_completed"

    class Record:
        execution_id = "a" * 32
        capability_identifier = "repository_analyzer"
        status = "SUCCEEDED"
        events = [Event()]

    monkeypatch.setattr("zeroagent.tui.history", lambda storage, limit: [Record()])
    monkeypatch.setattr(
        "zeroagent.tui.replay", lambda record: calls.append(record) or record
    )
    interface.handle("/history")
    interface.handle("enter")
    assert "capability_completed" in interface.state.message
    interface.handle("/replay")
    interface.handle("enter")
    assert calls == [interface.state.history_records[0]]
    assert "No capability will be executed" in interface.state.message
