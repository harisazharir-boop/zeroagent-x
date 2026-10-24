"""Structural verification for bounded repository context evidence."""

import hashlib

from zeroagent.context import ContextReport
from zeroagent.proof.models import CheckResult, EvidenceReference


def verify_context(report: ContextReport) -> list[CheckResult]:
    """Verify context metadata only; no claim about model answer correctness."""
    sources_valid = all(
        source.path
        and not source.path.startswith(("/", "\\"))
        and ".." not in source.path.replace("\\", "/").split("/")
        and source.sha256 == hashlib.sha256(source.content.encode("utf-8")).hexdigest()
        for source in report.sources
    )
    evidence = [
        EvidenceReference(
            reference_type="context_source", path=source.path, detail=source.sha256
        )
        for source in report.sources
    ]
    return [
        CheckResult(
            check_id="context.evidence",
            status="PASS" if sources_valid and report.sources else "INCOMPLETE",
            required=True,
            reason=(
                "Context source paths and hashes are structurally valid"
                if sources_valid and report.sources
                else "Context has no structurally verifiable source excerpts"
            ),
            evidence=evidence,
        ),
        CheckResult(
            check_id="context.semantic_correctness",
            status="INCOMPLETE",
            required=True,
            reason="Source citations do not verify AI explanation correctness",
        ),
    ]
