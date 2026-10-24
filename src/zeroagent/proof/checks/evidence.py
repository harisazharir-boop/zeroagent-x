"""Portable validation for untrusted evidence references."""

from pathlib import PurePath, PureWindowsPath

from zeroagent.core.repository import Evidence
from zeroagent.proof.models import CheckResult, EvidenceReference


def _safe_relative_path(value: str) -> bool:
    windows_path = PureWindowsPath(value)
    posix_path = PurePath(value)
    return (
        bool(value)
        and not windows_path.is_absolute()
        and not posix_path.is_absolute()
        and ".." not in windows_path.parts
        and ".." not in posix_path.parts
    )


def verify_evidence_paths(evidence: list[Evidence]) -> CheckResult:
    """Reject malformed, absolute, and parent-traversal report evidence paths."""
    if not evidence:
        return CheckResult(
            check_id="evidence.paths",
            status="INCOMPLETE",
            required=True,
            reason="Artifact has no evidence references",
        )
    references: list[EvidenceReference] = []
    for item in evidence:
        path = item.evidence.get("file")
        detector = item.evidence.get("detector")
        if not isinstance(path, str) or not _safe_relative_path(path):
            return CheckResult(
                check_id="evidence.paths",
                status="FAIL",
                required=True,
                reason="Evidence contains missing, absolute, or escaping file path",
            )
        if not isinstance(detector, str) or not detector:
            return CheckResult(
                check_id="evidence.paths",
                status="FAIL",
                required=True,
                reason="Evidence contains missing detector",
            )
        references.append(
            EvidenceReference(reference_type=item.finding_type, path=path)
        )
    return CheckResult(
        check_id="evidence.paths",
        status="PASS",
        required=True,
        reason="All evidence paths are portable relative paths",
        evidence=references,
    )
