"""Security tests for approval-bound controlled edits."""

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from zeroagent.cli import app
from zeroagent.editing import (
    EditError,
    FileChange,
    apply,
    approve,
    make_proposal,
    parse_ai_proposal,
    preview,
    recover,
    validate_proposal,
)

runner = CliRunner()


def change(
    path: str, original: str | None, new: str, operation: str = "modify"
) -> FileChange:
    return FileChange(
        path=path,
        operation=operation,
        original_sha256=hashlib.sha256(original.encode()).hexdigest()
        if original is not None
        else None,
        new_content=new,
        resulting_sha256=hashlib.sha256(new.encode()).hexdigest(),
    )


def test_preview_validation_and_exact_approval_apply_recovery(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_bytes(b"old\n")
    proposal = make_proposal(tmp_path, [change("app.py", "old\n", "new\n")], "update")
    validate_proposal(proposal, tmp_path)
    assert target.read_bytes() == b"old\n"
    diff = preview(proposal, tmp_path)
    assert "-old" in diff and "+new" in diff and proposal.digest
    approval = approve(proposal, tmp_path)
    recovery = tmp_path.parent / "recovery"
    result = apply(proposal, approval, tmp_path, recovery)
    assert (
        target.read_bytes() == b"new\n" and result.structural_status == "PATCH_APPLIED"
    )
    assert recover(recovery, tmp_path) == ["app.py"]
    assert target.read_bytes() == b"old\n"


@pytest.mark.parametrize("original", [b"old\n", b"old\r\n"])
def test_edit_digest_validates_exact_newline_bytes(
    tmp_path: Path, original: bytes
) -> None:
    target = tmp_path / "app.py"
    target.write_bytes(original)
    proposal = make_proposal(
        tmp_path,
        [change("app.py", original.decode(), "new\n")],
        "update",
    )
    validate_proposal(proposal, tmp_path)
    target.write_bytes(original.replace(b"\n", b"\nchanged"))
    with pytest.raises(EditError, match="Stale"):
        validate_proposal(proposal, tmp_path)


@pytest.mark.parametrize("path", ["../x.py", ".git/config", ".env", "secret.key"])
def test_unsafe_targets_rejected(tmp_path: Path, path: str) -> None:
    proposal = make_proposal(tmp_path, [change(path, None, "x", "create")], "bad")
    with pytest.raises(EditError):
        validate_proposal(proposal, tmp_path)


def test_stale_or_wrong_approval_rejected(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("old")
    proposal = make_proposal(tmp_path, [change("app.py", "old", "new")], "update")
    approval = approve(proposal, tmp_path)
    target.write_text("other")
    with pytest.raises(EditError, match="Stale"):
        apply(proposal, approval, tmp_path, tmp_path.parent / "recovery")


def test_ai_json_parser_rejects_malformed_and_unsafe(tmp_path: Path) -> None:
    with pytest.raises(EditError):
        parse_ai_proposal("not json", tmp_path)
    unsafe = (
        '{"changes":[{"path":"../bad.py","operation":"create",'
        '"new_content":"x","resulting_sha256":"0"}],"explanation":"x"}'
    )
    with pytest.raises(EditError):
        parse_ai_proposal(unsafe, tmp_path)


def test_edit_audit_is_opt_in_and_excludes_content(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("old")
    proposal = make_proposal(tmp_path, [change("app.py", "old", "new")], "update")
    proposal_file = tmp_path / "proposal.json"
    proposal_file.write_text(proposal.model_dump_json())
    recovery = tmp_path.parent / "recovery-audit"
    storage = tmp_path.parent / "audit-store"
    result = runner.invoke(
        app,
        [
            "edit",
            "apply",
            str(proposal_file),
            "--workspace",
            str(tmp_path),
            "--approve-digest",
            proposal.digest,
            "--recovery-dir",
            str(recovery),
            "--record",
            "--storage-dir",
            str(storage),
        ],
    )
    assert result.exit_code == 0 and '"audit": "recorded"' in result.output
    raw = next(storage.glob("*.json")).read_text()
    assert "proposal_digest" in raw and "new_content" not in raw and "old" not in raw
