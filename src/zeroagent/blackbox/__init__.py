"""Opt-in local execution history, inspection, and historical replay."""

from zeroagent.blackbox.recorder import Recorder
from zeroagent.blackbox.storage import LocalStorage, StorageError

__all__ = ["LocalStorage", "Recorder", "StorageError"]
