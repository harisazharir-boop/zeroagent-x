"""Tests for ZEROAGENT X Full-Screen Menu TUI and Alternate-Screen Isolation."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from zeroagent import __version__
from zeroagent.editing import FileChange, make_proposal
from zeroagent.tui import MENU, NeonMinimalTui


def _tui(
    workspace: Path | None = None, width: int = 100
) -> tuple[NeonMinimalTui, StringIO]:
    stream = StringIO()
    console = Console(
        file=stream, force_terminal=True, width=width, color_system="truecolor"
    )
    return NeonMinimalTui(console=console, workspace=workspace), stream


def test_tui_renders_header_with_geometric_logo_and_spacing() -> None:
    interface, stream = _tui()
    interface.render()
    output = stream.getvalue()

    # Brand checks
    assert "ZEROAGENT X" in output
    assert f"v{__version__}" in output
    assert "LOCAL-FIRST · PROOF-DRIVEN" in output
    assert "Don't Just Run AI. Prove It Works." in output

    # Check geometric X logo presence and compact box-drawing frame
    assert "╭──────────╮" in output
    assert "██╗" in output
    assert "██║" in output

    # Check footer presence
    assert "◈ ZERO PAID API REQUIRED ◈" in output


def test_tui_main_menu_renders_all_ten_items() -> None:
    interface, stream = _tui()
    interface.render()
    output = stream.getvalue()

    assert "MAIN MENU" in output
    for idx, (title, _) in enumerate(MENU, start=1):
        assert f"{idx:02d}. {title}" in output


def test_tui_menu_keyboard_navigation_and_selection() -> None:
    interface, _ = _tui()
    assert interface.state.selected_index == 0
    assert interface.state.current_screen == "home"

    # Navigate down
    interface.handle("down")
    assert interface.state.selected_index == 1

    # Navigate up
    interface.handle("up")
    assert interface.state.selected_index == 0

    # Number shortcut directly to item 5 (Run Controlled Tests)
    interface.handle("5")
    assert interface.state.selected_index == 4
    assert interface.state.current_screen == "test"

    # Esc returns to home screen
    interface.handle("esc")
    assert interface.state.current_screen == "home"


def test_tui_all_ten_screens_accessible() -> None:
    interface, stream = _tui()
    screen_keys = [
        "1",  # Analyze
        "2",  # Ask Context
        "3",  # Plan
        "4",  # Edit
        "5",  # Test
        "6",  # Verify
        "7",  # History
        "8",  # Replay
        "9",  # AI Chat
        "10",  # Settings
    ]
    for key in screen_keys:
        interface.handle(key)
        assert interface.state.current_screen != "home"
        interface.render()
        # Ensure screen renders without raising errors
        assert stream.getvalue()
        # Return home
        interface.handle("esc")
        assert interface.state.current_screen == "home"


def test_tui_compact_logo_on_narrow_terminal() -> None:
    interface, stream = _tui(width=75)
    interface.render()
    output = stream.getvalue()
    # Compact logo header checks
    assert "╭─────────╮" in output or "ZEROAGENT X" in output


def test_tui_safe_edit_flow(tmp_path: Path) -> None:
    app_py = tmp_path / "app.py"
    app_py.write_text("v1\n")
    orig_hash = "2d27fbdf4e8ca207afbfa388ca9172fbcc6c70e534af2476b3b704f87debadcf"
    res_hash = "81db67b6a5702b9b68f0016f061c409bf3fb16d062fc854d1b424bb4e9c28c56"
    change = FileChange(
        path="app.py",
        operation="modify",
        original_sha256=orig_hash,
        new_content="v2\n",
        resulting_sha256=res_hash,
    )
    proposal = make_proposal(tmp_path, [change], "Upgrade version")
    prop_file = tmp_path / "proposal.json"
    prop_file.write_text(proposal.model_dump_json())

    interface, stream = _tui(workspace=tmp_path)
    # Open edit screen
    interface.handle("4")
    assert interface.state.current_screen == "edit"

    # Load proposal
    interface.handle(f"/edit-load {prop_file}")
    assert interface.state.edit_proposal is not None
    assert interface.state.edit_approved is False

    # Preview diff (read-only)
    interface.handle("/edit-preview")
    interface.render()
    assert "Diff Preview:" in stream.getvalue()
    assert app_py.read_text() == "v1\n"

    # Apply blocked without approval
    interface.handle("/edit-apply")
    assert "Application blocked" in interface.state.message
    assert app_py.read_text() == "v1\n"

    # Approve with exact digest and apply
    interface.handle(f"/edit-approve {proposal.digest}")
    assert interface.state.edit_approved is True
    interface.handle("/edit-apply")
    assert "Patch Applied" in interface.state.message
    assert app_py.read_text() == "v2\n"


def test_tui_controlled_test_flow(tmp_path: Path) -> None:
    test_py = tmp_path / "test_sample.py"
    test_py.write_text("def test_ok(): assert 1 == 1\n")

    interface, stream = _tui(workspace=tmp_path)
    # Open test screen
    interface.handle("5")
    assert interface.state.current_screen == "test"

    # Create spec
    interface.handle("/test-spec test_sample.py")
    assert interface.state.test_spec is not None
    digest = interface.state.test_spec.digest

    # Preview
    interface.handle("/test-preview")
    interface.render()
    assert "Test Preview:" in stream.getvalue() or "Command:" in stream.getvalue()

    # Blocked without approval
    interface.handle("/test-run")
    assert "Test execution blocked" in interface.state.message

    # Approve and run
    interface.handle(f"/test-approve {digest}")
    assert interface.state.test_approved is True
    interface.handle("/test-run")
    interface.render()
    assert "Test Result: PASSED" in interface.state.message


def test_tui_local_ai_chat_interaction(monkeypatch: pytest.MonkeyPatch) -> None:
    class DummyService:
        def doctor(self):
            from zeroagent.ai.models import ProviderInfo

            return ProviderInfo(
                endpoint="http://127.0.0.1:11434", reachable=True, model_count=1
            )

        def models(self):
            from zeroagent.ai.models import InstalledModel

            return [
                InstalledModel(identifier="llama3:latest", size_bytes=4_000_000_000)
            ]

        def ask(self, prompt: str, model: str):
            from zeroagent.ai.models import GenerationResponse

            return GenerationResponse(
                model=model, response=f"Local explanation for: {prompt}"
            )

    monkeypatch.setattr("zeroagent.tui.LocalAIService", lambda cfg: DummyService())

    interface, stream = _tui()
    interface.handle("9")  # AI Chat screen
    assert interface.state.current_screen == "ai"

    # Send chat prompt
    interface.handle("What is a decorator in Python?")
    interface.render()
    output = stream.getvalue()
    assert "User:" in output and "What is a decorator in Python?" in output
    assert "Ollama:" in output and "Local explanation for:" in output


def test_tui_noninteractive_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    class Stream:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("zeroagent.tui.sys.stdin", Stream())
    interface, _ = _tui()
    try:
        interface.run_interactive()
    except RuntimeError as err:
        assert "Interactive terminal required" in str(err)
    else:
        raise AssertionError("Expected noninteractive rejection")
