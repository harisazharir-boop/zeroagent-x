"""Structural evidence checks for controlled test execution."""

from zeroagent.proof.models import CheckResult
from zeroagent.testing import TestEvidence


def verify_test(evidence: TestEvidence) -> list[CheckResult]:
    return [
        CheckResult(
            check_id="tests.specification_valid",
            status="PASS" if len(evidence.specification_digest) == 64 else "FAIL",
            required=True,
            reason="Test specification digest has expected SHA-256 length",
        ),
        CheckResult(
            check_id="tests.approval_bound",
            status="PASS" if evidence.approval_bound else "FAIL",
            required=True,
            reason="Approval is bound to exact test specification",
        ),
        CheckResult(
            check_id="tests.runner_allowlisted",
            status="PASS" if evidence.runner_allowlisted else "FAIL",
            required=True,
            reason="Runner is verified against strict allowlist",
        ),
        CheckResult(
            check_id="tests.execution_completed",
            status="PASS" if evidence.execution_completed else "FAIL",
            required=True,
            reason="Test process completed execution without hanging or aborting",
        ),
        CheckResult(
            check_id="tests.exit_code_zero",
            status="PASS" if evidence.exit_code_zero else "FAIL",
            required=True,
            reason="Test process returned exit code 0",
        ),
        CheckResult(
            check_id="tests.output_integrity",
            status="PASS" if evidence.output_integrity else "INCOMPLETE",
            required=True,
            reason="Process output stream integrity verified",
        ),
        CheckResult(
            check_id="tests.semantic_correctness",
            status="INCOMPLETE",
            required=True,
            reason="Passing test suite verifies tested conditions only",
        ),
    ]
