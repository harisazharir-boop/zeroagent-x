"""Request fingerprints and local, opaque, single-use execution approvals."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from zeroagent.blackbox.storage import LocalStorage, default_storage_dir
from zeroagent.config import Settings, load_settings
from zeroagent.execution.adapters import OpenCodeAdapter
from zeroagent.execution.coordinator import ExecutionCoordinator
from zeroagent.execution.models import ExecutionRequest
from zeroagent.execution.registry import AdapterRegistry


class ApprovalError(RuntimeError):
    """Raised for invalid, expired, consumed, or mismatched local authorization."""


def request_digest(
    *,
    adapter_id: str,
    workspace: Path,
    prompt: str,
    timeout_seconds: int | None,
    record_evidence: bool,
    settings: Settings | None = None,
) -> str:
    """Fingerprint request and policy; never an authorization credential."""
    active = settings or load_settings()
    fields = {
        "adapter_id": adapter_id,
        "workspace": str(workspace.expanduser().resolve()),
        "prompt": prompt,
        "timeout_seconds": timeout_seconds,
        "record_evidence": record_evidence,
        "agent_execution_enabled": active.agent_execution_enabled,
        "opencode_enabled": active.opencode_enabled,
        "network_enabled": active.network_enabled,
        "default_timeout_seconds": active.agent_execution_timeout_seconds,
    }
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ApprovalStore:
    """Local opaque tokens bind one fingerprint, expire, and are consumed once."""

    _lock = threading.Lock()

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_storage_dir().parent / "approvals"

    def _path(self, token: str) -> Path:
        if len(token) != 64 or any(char not in "0123456789abcdef" for char in token):
            raise ApprovalError("Invalid approval authorization")
        return self.root / f"{token}.json"

    def issue(self, fingerprint: str, *, lifetime_seconds: int = 300) -> str:
        token = secrets.token_hex(32)
        data = {
            "fingerprint": fingerprint,
            "expires_at": (
                datetime.now(UTC) + timedelta(seconds=lifetime_seconds)
            ).isoformat(),
        }
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                self.root.chmod(0o700)
            path = self._path(token)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, separators=(",", ":"))
        except OSError as error:
            raise ApprovalError(
                "Cannot persist local approval authorization"
            ) from error
        return token

    def consume(self, token: str | None, fingerprint: str) -> bool:
        if token is None:
            return False
        try:
            path = self._path(token)
        except ApprovalError:
            return False
        with self._lock:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                path.unlink()
            except (OSError, json.JSONDecodeError):
                return False
        try:
            expires = datetime.fromisoformat(data["expires_at"])
            return data["fingerprint"] == fingerprint and expires > datetime.now(UTC)
        except (KeyError, TypeError, ValueError):
            return False


def make_request(
    *,
    adapter_id: str,
    workspace: Path,
    prompt: str,
    timeout_seconds: int | None,
    record_evidence: bool,
    approval_token: str | None = None,
) -> ExecutionRequest:
    return ExecutionRequest(
        adapter_id=adapter_id,
        workspace=workspace,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        record_evidence=record_evidence,
        approval_token=approval_token,
    )


def make_coordinator(
    *,
    settings: Settings | None = None,
    storage_dir: Path | None = None,
    approval_store: ApprovalStore | None = None,
) -> ExecutionCoordinator:
    """Build registered adapter and coordinator-owned opaque authorization check."""
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
    approvals = approval_store or ApprovalStore()

    def authorize(request: ExecutionRequest) -> bool:
        fingerprint = request_digest(
            adapter_id=request.adapter_id,
            workspace=request.workspace,
            prompt=request.prompt,
            timeout_seconds=request.timeout_seconds,
            record_evidence=request.record_evidence,
            settings=active_settings,
        )
        return approvals.consume(request.approval_token, fingerprint)

    return ExecutionCoordinator(
        AdapterRegistry([adapter]),
        settings=active_settings,
        storage=storage,
        approval_authorizer=authorize,
    )
