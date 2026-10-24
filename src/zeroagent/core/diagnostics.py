"""Local runtime diagnostics shared by CLI and routed capability handlers."""

import platform
from pathlib import Path

from zeroagent import __version__
from zeroagent.config import Settings


def collect_diagnostics(settings: Settings) -> dict[str, str]:
    """Return actual local diagnostic values without network access."""
    return {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "current_directory": str(Path.cwd()),
        "telemetry": "enabled" if settings.telemetry_enabled else "disabled",
        "network_access": "enabled" if settings.network_enabled else "disabled",
        "shell_command_execution": (
            "enabled" if settings.shell_command_execution_enabled else "disabled"
        ),
    }
