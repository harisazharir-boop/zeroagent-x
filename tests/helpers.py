"""Rendered Textual screen helpers for compositor-level regression tests."""

from __future__ import annotations

from rich.cells import cell_len
from textual.app import App


async def render_lines(app: App, size: tuple[int, int]) -> list[str]:
    """Render current app screen through Textual's compositor strips."""
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        strips = app.screen._compositor.render_strips()  # noqa: SLF001
        lines = [strip.text for strip in strips]
        return [line + " " * max(0, size[0] - cell_len(line)) for line in lines]


async def render_cells(app: App, size: tuple[int, int]) -> list[list[tuple[str, str]]]:
    """Return rendered character/style cells from compositor strips."""
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        strips = app.screen._compositor.render_strips()  # noqa: SLF001
        output: list[list[tuple[str, str]]] = []
        for strip in strips:
            cells: list[tuple[str, str]] = []
            for segment in strip:
                for character in segment.text:
                    cells.append((character, str(segment.style)))
                    cells.extend(
                        ("", str(segment.style)) for _ in range(cell_len(character) - 1)
                    )
            output.append((cells + [(" ", "") for _ in range(size[0])])[: size[0]])
        return output


def format_dump(lines: list[str], x0: int, x1: int, y0: int, y1: int) -> str:
    """Format cropped screen lines with a repeating column ruler."""
    ruler = "".join(str(column % 10) for column in range(x0, x1))
    body = [f"{row:02d} {lines[row][x0:x1]}" for row in range(y0, min(y1, len(lines)))]
    return "\n".join([f"   {ruler}", *body])
