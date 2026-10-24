"""Structural evidence checks for controlled patch application."""

from zeroagent.editing import PatchEvidence
from zeroagent.proof.models import CheckResult


def verify_patch(evidence: PatchEvidence) -> list[CheckResult]:
    return [
        CheckResult(
            check_id="patch.digest_consistent",
            status="PASS" if len(evidence.proposal_digest) == 64 else "FAIL",
            required=True,
            reason="Proposal digest has expected SHA-256 length",
        ),
        CheckResult(
            check_id="patch.approval_bound",
            status="PASS" if evidence.approval_bound else "FAIL",
            required=True,
            reason="Approval is bound to exact proposal",
        ),
        CheckResult(
            check_id="patch.result_hashes_match",
            status="PASS" if evidence.applied_paths else "INCOMPLETE",
            required=True,
            reason="Applied result paths recorded",
        ),
        CheckResult(
            check_id="patch.recovery_metadata_present",
            status="PASS" if evidence.recovery_present else "FAIL",
            required=True,
            reason="Recovery metadata is present",
        ),
        CheckResult(
            check_id="patch.permissions_preserved",
            status="PASS" if evidence.permissions_preserved else "FAIL",
            required=True,
            reason="Target permission modes were verified",
        ),
        CheckResult(
            check_id="patch.semantic_correctness",
            status="INCOMPLETE",
            required=True,
            reason="Applied bytes do not establish code correctness or test success",
        ),
    ]
