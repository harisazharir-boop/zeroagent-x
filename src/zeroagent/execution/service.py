"""Application-facing factory and request helpers for governed agent execution."""

from __future__ import annotations

import hashlib
from pathlib import Path

from zeroagent.blackbox.storage import LocalStorage
from zeroagent.config import Settings, load_settings
from zeroagent.execution.adapters import OpenCodeAdapter
from zeroagent.execution.coordinator import ExecutionCoordinator
from zeroagent.execution.models import ExecutionRequest
from zeroagent.execution.registry import AdapterRegistry


def request_digest(
    *,
    adapter_id: str,
    workspace: Path,
    prompt: str,
    timeout_seconds: int | None,
    record_evidence: bool,
) -> str:
    """Stable, displayable approval binding for all material request fields."""
    fields = "\n".join(
        (
            adapter_id,
            str(workspace.resolve()),
            prompt,
            str(timeout_seconds),
            str(record_evidence),
        )
    )
    return hashlib.sha256(fields.encode("utf-8")).hexdigest()


def make_request(
    *,
    adapter_id: str,
    workspace: Path,
    prompt: str,
    timeout_seconds: int | None,
    record_evidence: bool,
    approval_digest: str | None,
) -> ExecutionRequest:
    digest = request_digest(
        adapter_id=adapter_id,
        workspace=workspace,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        record_evidence=record_evidence,
    )
    return ExecutionRequest(
        adapter_id=adapter_id,
        workspace=workspace,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        record_evidence=record_evidence,
        approved=approval_digest == digest,
    )


def make_coordinator(
    *,
    settings: Settings | None = None,
    storage_dir: Path | None = None,
) -> ExecutionCoordinator:
    """Build only registered adapters; callers never invoke subprocesses directly."""
    active_settings = settings or load_settings()
    storage_root = storage_dir or (
        Path(active_settings.blackbox_storage_dir)
        if active_settings.blackbox_storage_dir
        else None
    )
    adapter = OpenCodeAdapter(
        active_settings.opencode_executable or "opencode",
        max_output_bytes=active_settings.agent_execution_max_output_bytes,
    )
    storage = LocalStorage(
        storage_root,
        max_records=active_settings.blackbox_max_records,
        max_record_bytes=active_settings.blackbox_max_record_bytes,
        max_age_days=active_settings.blackbox_max_record_age_days,
    )
    return ExecutionCoordinator(
        AdapterRegistry([adapter]), settings=active_settings, storage=storage
    )
