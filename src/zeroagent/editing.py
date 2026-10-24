"""Controlled, approval-bound, text-only workspace editing primitives."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from zeroagent.context import SENSITIVE_NAMES, SENSITIVE_SUFFIXES
from zeroagent.security.workspace import validate_workspace

MAX_FILES = 5
MAX_FILE_BYTES = 65_536
MAX_TOTAL_BYTES = 262_144
PATH_PATTERN = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")


class EditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FileChange(EditModel):
    path: str
    operation: str
    original_sha256: str | None = None
    new_content: str = Field(max_length=MAX_FILE_BYTES)
    resulting_sha256: str


class PatchProposal(EditModel):
    schema_version: str = "1"
    proposal_id: str
    workspace_identifier: str
    changes: list[FileChange] = Field(min_length=1, max_length=MAX_FILES)
    explanation: str = Field(max_length=16_384)
    digest: str


class PatchApproval(EditModel):
    proposal_id: str
    proposal_digest: str
    workspace_identifier: str


class ApplicationResult(EditModel):
    application_id: str
    proposal_digest: str
    applied_paths: list[str]
    recovery_path: str
    structural_status: str


class PatchEvidence(EditModel):
    proposal_digest: str
    approval_bound: bool
    applied_paths: list[str] = []
    recovery_present: bool = False
    permissions_preserved: bool = False


class EditError(ValueError):
    pass


def _digest_payload(proposal: PatchProposal) -> str:
    payload = proposal.model_dump(exclude={"digest"}, mode="json")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def make_proposal(
    workspace: Path, changes: list[FileChange], explanation: str
) -> PatchProposal:
    root = validate_workspace(workspace)
    draft = PatchProposal(
        proposal_id=uuid4().hex,
        workspace_identifier=root.name,
        changes=changes,
        explanation=explanation,
        digest="",
    )
    return draft.model_copy(update={"digest": _digest_payload(draft)})


def parse_ai_proposal(payload: str, workspace: Path) -> PatchProposal:
    """Parse untrusted model JSON, recompute digest, then validate workspace targets."""
    try:
        data = json.loads(payload)
        changes = [FileChange.model_validate(item) for item in data["changes"]]
        explanation = data.get("explanation", "Local model proposal")
    except (ValueError, KeyError, TypeError) as error:
        raise EditError("Model response is not valid structured patch JSON") from error
    return validate_proposal(make_proposal(workspace, changes, explanation), workspace)


def load_proposal(path: Path) -> PatchProposal:
    """Load bounded untrusted structured proposal without evaluation."""
    if path.is_symlink() or path.stat().st_size > 1_000_000:
        raise EditError("Proposal file is unsafe or exceeds size limit")
    try:
        return PatchProposal.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise EditError("Proposal file is invalid") from error


def _safe_target(root: Path, relative: str, creation: bool) -> Path:
    if not PATH_PATTERN.fullmatch(relative) or relative.startswith(".git/"):
        raise EditError(f"Unsafe target path: {relative}")
    path = root / relative
    name = path.name.casefold()
    parts = {part.casefold() for part in Path(relative).parts}
    if (
        name == ".env"
        or name.startswith(".env.")
        or name in SENSITIVE_NAMES
        or name.endswith(SENSITIVE_SUFFIXES)
    ):
        raise EditError(f"Sensitive target prohibited: {relative}")
    if parts & {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "build",
        "dist",
        "__pycache__",
    }:
        raise EditError(f"Protected target prohibited: {relative}")
    parent = path.parent.resolve(strict=True)
    if root not in (parent, *parent.parents) or any(
        part.is_symlink() for part in [path, *path.parents] if part.exists()
    ):
        raise EditError(f"Symlink or containment violation: {relative}")
    if creation and path.exists():
        raise EditError(f"Creation target already exists: {relative}")
    return path


def preview(proposal: PatchProposal, workspace: Path, max_lines: int = 500) -> str:
    """Build bounded unified diff after validation without modifying workspace."""
    root = validate_workspace(workspace)
    validate_proposal(proposal, root)
    lines: list[str] = []
    for change in proposal.changes:
        before = (
            []
            if change.operation == "create"
            else (root / change.path)
            .read_text(encoding="utf-8")
            .splitlines(keepends=True)
        )
        after = change.new_content.splitlines(keepends=True)
        lines.extend(
            difflib.unified_diff(
                before, after, fromfile=f"a/{change.path}", tofile=f"b/{change.path}"
            )
        )
        if len(lines) >= max_lines:
            lines.append(
                "... diff truncated; complete bounded proposal content remains "
                "in proposal file ...\n"
            )
            break
    return "".join(lines[: max_lines + 1])


def validate_proposal(proposal: PatchProposal, workspace: Path) -> PatchProposal:
    root = validate_workspace(workspace)
    if proposal.workspace_identifier != root.name or proposal.digest != _digest_payload(
        proposal
    ):
        raise EditError("Proposal workspace or digest mismatch")
    paths: set[str] = set()
    total = 0
    for change in proposal.changes:
        if change.path in paths or change.operation not in {"modify", "create"}:
            raise EditError("Duplicate target or unsupported operation")
        paths.add(change.path)
        path = _safe_target(root, change.path, change.operation == "create")
        encoded = change.new_content.encode("utf-8")
        total += len(encoded)
        if len(encoded) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise EditError("Proposal content exceeds configured limits")
        if hashlib.sha256(encoded).hexdigest() != change.resulting_sha256:
            raise EditError(f"Result hash mismatch: {change.path}")
        if change.operation == "modify":
            if (
                not path.exists()
                or path.is_symlink()
                or not path.is_file()
                or change.original_sha256 is None
            ):
                raise EditError(f"Invalid modification target: {change.path}")
            if path.stat().st_nlink > 1:
                raise EditError(f"Hard-linked target prohibited: {change.path}")
            if path.stat().st_size > MAX_FILE_BYTES:
                raise EditError(f"Oversized modification target: {change.path}")
            if hashlib.sha256(path.read_bytes()).hexdigest() != change.original_sha256:
                raise EditError(f"Stale proposal: {change.path}")
    return proposal


def approve(proposal: PatchProposal, workspace: Path) -> PatchApproval:
    root = validate_workspace(workspace)
    validate_proposal(proposal, root)
    return PatchApproval(
        proposal_id=proposal.proposal_id,
        proposal_digest=proposal.digest,
        workspace_identifier=root.name,
    )


def apply(
    proposal: PatchProposal,
    approval: PatchApproval,
    workspace: Path,
    recovery_root: Path,
) -> ApplicationResult:
    root = validate_workspace(workspace)
    if (
        approval.proposal_id != proposal.proposal_id
        or approval.proposal_digest != proposal.digest
        or approval.workspace_identifier != root.name
    ):
        raise EditError("Approval is not bound to this exact proposal and workspace")
    validate_proposal(proposal, root)
    application_id = uuid4().hex
    recovery_parent = recovery_root.resolve().parent
    if root in (recovery_parent, *recovery_parent.parents):
        raise EditError("Recovery directory must be outside workspace")
    recovery_root.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest: dict[str, object] = {
        "schema_version": "1",
        "application_id": application_id,
        "proposal_digest": proposal.digest,
        "workspace_identifier": root.name,
        "files": [],
    }
    applied: list[str] = []
    try:
        for index, change in enumerate(proposal.changes):
            target = _safe_target(root, change.path, change.operation == "create")
            original = target.read_bytes() if change.operation == "modify" else None
            original_mode = (
                target.stat().st_mode & 0o777 if original is not None else 0o600
            )
            if original_mode & 0o6000:
                raise EditError(f"Unsafe special permissions: {change.path}")
            backup = recovery_root / f"{index}.bak"
            if original is not None:
                backup.write_bytes(original)
                if os.name != "nt":
                    backup.chmod(0o600)
            manifest["files"].append(
                {
                    "path": change.path,
                    "operation": change.operation,
                    "backup": backup.name if original is not None else None,
                    "resulting_sha256": change.resulting_sha256,
                    "mode": original_mode,
                }
            )
            descriptor, temporary = tempfile.mkstemp(
                prefix=".zeroagent-edit-", dir=target.parent
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(change.new_content.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                os.chmod(temporary, original_mode)
            os.replace(temporary, target)
            if (
                hashlib.sha256(target.read_bytes()).hexdigest()
                != change.resulting_sha256
            ):
                raise EditError(f"Post-write hash mismatch: {change.path}")
            if os.name != "nt" and target.stat().st_mode & 0o777 != original_mode:
                raise EditError(f"Permission mode mismatch: {change.path}")
            applied.append(change.path)
    except Exception as error:
        raise EditError(
            f"Application partially applied: {applied}; recovery retained"
        ) from error
    (recovery_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return ApplicationResult(
        application_id=application_id,
        proposal_digest=proposal.digest,
        applied_paths=applied,
        recovery_path=str(recovery_root),
        structural_status="PATCH_APPLIED",
    )


def recover(recovery_root: Path, workspace: Path) -> list[str]:
    """Explicit best-effort restore only when edited files remain unchanged."""
    root = validate_workspace(workspace)
    try:
        if recovery_root.is_symlink():
            raise EditError("Recovery directory must not be a symbolic link")
        manifest = json.loads(
            (recovery_root / "manifest.json").read_text(encoding="utf-8")
        )
        files = manifest["files"]
        if (
            manifest["schema_version"] != "1"
            or manifest["workspace_identifier"] != root.name
        ):
            raise EditError("Recovery manifest workspace or schema mismatch")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise EditError("Recovery metadata is invalid") from error
    restored: list[str] = []
    for item in files:
        target = _safe_target(root, item["path"], item["operation"] == "create")
        if not isinstance(item.get("mode"), int):
            raise EditError("Recovery manifest has invalid mode")
        current_hash = (
            hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        )
        if current_hash != item["resulting_sha256"]:
            raise EditError(f"Recovery refused after subsequent change: {item['path']}")
        if item["operation"] == "create":
            target.unlink()
        else:
            os.replace(recovery_root / item["backup"], target)
            if os.name != "nt":
                os.chmod(target, item["mode"])
        restored.append(item["path"])
    return restored
