"""Typed models for deterministic evidence-based verification."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

CheckStatus = Literal["PASS", "FAIL", "INCOMPLETE", "NOT_APPLICABLE"]
ProofStatus = Literal["VERIFIED", "FAILED", "INCOMPLETE"]


class ProofModel(BaseModel):
    """Strict immutable base for proof records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceReference(ProofModel):
    reference_type: str
    path: str | None = None
    detail: str | None = None


class VerificationClaim(ProofModel):
    claim_type: str
    description: str
    required: bool = True


class VerificationRequest(ProofModel):
    artifact_type: str
    workspace_identifier: str | None = None
    claims: list[VerificationClaim]


class CheckResult(ProofModel):
    check_id: str
    status: CheckStatus
    required: bool
    reason: str
    evidence: list[EvidenceReference] = []


class ProofReport(ProofModel):
    schema_version: str = "1.0"
    artifact_type: str
    overall_status: ProofStatus
    checks: list[CheckResult]


def aggregate_status(checks: list[CheckResult]) -> ProofStatus:
    """Apply required-check aggregation rules without collapsing results to bool."""
    required_applicable = [
        check for check in checks if check.required and check.status != "NOT_APPLICABLE"
    ]
    if any(check.status == "FAIL" for check in required_applicable):
        return "FAILED"
    if any(check.status == "INCOMPLETE" for check in required_applicable):
        return "INCOMPLETE"
    if not required_applicable:
        return "INCOMPLETE"
    return "VERIFIED"
