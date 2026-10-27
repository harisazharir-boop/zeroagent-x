"""Official ZEROAGENT X logo asset resolver and capability-aware terminal renderer."""

from __future__ import annotations

import base64
import os
import struct
from importlib import resources
from pathlib import Path
from typing import NamedTuple


class ImageMetadata(NamedTuple):
    path: Path
    width: int
    height: int
    color_type: int
    size_bytes: int


def resolve_logo_asset() -> Path | None:
    """Find authoritative assets/logo.png from workspace root or installed package."""
    # 1. Check workspace/dev assets directory
    repo_asset = Path.cwd() / "assets" / "logo.png"
    if repo_asset.is_file():
        return repo_asset

    # 2. Check parent directories (if run from a subdirectory)
    for parent in Path.cwd().parents:
        cand = parent / "assets" / "logo.png"
        if cand.is_file():
            return cand

    # 3. Check installed package data
    try:
        traversable = resources.files("zeroagent").joinpath("assets/logo.png")
        if traversable.is_file():
            return Path(str(traversable))
    except (TypeError, ModuleNotFoundError, AttributeError):
        pass

    return None


def get_logo_metadata() -> ImageMetadata | None:
    """Read metadata (dimensions, color type, size) from authoritative logo PNG."""
    path = resolve_logo_asset()
    if not path or not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            header = f.read(24)
            if header[:8] != b"\x89PNG\r\n\x1a\n":
                return None
            width, height = struct.unpack(">II", header[16:24])
            color_type = f.read(2)[1]
            size_bytes = path.stat().st_size
            return ImageMetadata(
                path=path,
                width=width,
                height=height,
                color_type=color_type,
                size_bytes=size_bytes,
            )
    except Exception:
        return None


def detect_terminal_image_support() -> str:
    """Detect whether current terminal supports inline graphical image protocols.

    Returns:
        "kitty" if Kitty graphics protocol is genuinely supported,
        "iterm2" if iTerm2 OSC 1337 protocol is supported,
        "none" if standard terminal without verified graphical image protocol.
    """
    # 1. Kitty protocol detection
    kitty_window = os.environ.get("KITTY_WINDOW_ID")
    term = os.environ.get("TERM", "")
    if kitty_window or "kitty" in term.lower():
        return "kitty"

    # 2. iTerm2 / WezTerm / Ghostty detection
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if (
        "iterm" in term_program
        or "wezterm" in term_program
        or "ghostty" in term_program
    ):
        return "iterm2"

    return "none"


def render_iterm2_graphics(png_path: Path, width_cols: int = 4) -> str:
    """Generate iTerm2 OSC 1337 inline image escape code."""
    try:
        content = png_path.read_bytes()
        b64 = base64.b64encode(content).decode("ascii")
        return f"\033]1337;File=inline=1;width={width_cols}:{b64}\a"
    except Exception:
        return ""


def render_kitty_graphics(png_path: Path, width_cols: int = 4) -> str:
    """Generate Kitty graphics escape sequence using file transmission (t=f).

    Using t=f passes the local absolute file path directly to Kitty without
    dumping megabytes of base64 data into the terminal stream, avoiding buffer
    exhaustion and text-wrapping hang in Textual/Rich rendering pipelines.
    """
    try:
        abs_path = str(png_path.resolve())
        path_b64 = base64.b64encode(abs_path.encode("utf-8")).decode("ascii")
        return f"\033_Ga=T,f=100,t=f,c={width_cols};{path_b64}\033\\"
    except Exception:
        return ""
