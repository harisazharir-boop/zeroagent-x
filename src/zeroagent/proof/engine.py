"""ProofEngine orchestration for routed local execution artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from zeroagent.ai.models import GenerationResponse
from zeroagent.config import Settings, load_settings
from zeroagent.context import ContextReport
from zeroagent.core.repository import AnalysisReport
from zeroagent.proof.checks.ai import verify_ai_response
from zeroagent.proof.checks.context import verify_context
from zeroagent.proof.checks.repository import verify_repository_report
from zeroagent.proof.checks.routing import verify_routing
from zeroagent.proof.models import CheckResult, ProofReport, aggregate_status
from zeroagent.proof.registry import VerificationCheck, VerificationRegistry
from zeroagent.routing.router import (
    CapabilityRegistry,
    RoutingDecision,
    default_registry,
)


def default_verification_registry() -> VerificationRegistry:
    """Create static built-in check registry without plugin discovery."""
    return VerificationRegistry(
        [
            VerificationCheck(
                "routing.decision",
                frozenset({"repository_report", "unsupported"}),
                verify_routing,
            ),
            VerificationCheck(
                "repository.report",
                frozenset({"repository_report"}),
                verify_repository_report,
            ),
            VerificationCheck(
                "ai.response",
                frozenset({"ai_response"}),
                verify_ai_response,
            ),
            VerificationCheck(
                "context.report",
                frozenset({"context_report"}),
                verify_context,
            ),
        ]
    )


def verify_execution(
    decision: RoutingDecision,
    result: Any,
    workspace: Path | None,
    *,
    settings: Settings | None = None,
    registry: CapabilityRegistry | None = None,
) -> ProofReport:
    """Verify actual result consistency with routing and supported artifact rules."""
    del (
        workspace
    )  # Report evidence is checked as relative data; no file execution or reads occur.
    active_settings = settings or load_settings()
    active_registry = registry or default_registry()
    artifact_type = "unsupported"
    if isinstance(result, AnalysisReport):
        artifact_type = "repository_report"
    elif isinstance(result, GenerationResponse):
        artifact_type = "ai_response"
    elif isinstance(result, ContextReport):
        artifact_type = "context_report"
    checks: list[CheckResult] = []
    for check in default_verification_registry().for_artifact(artifact_type):
        if check.identifier == "routing.decision":
            checks.append(check.handler(decision, active_registry, active_settings))
        elif check.identifier == "repository.report":
            checks.extend(check.handler(result))
        elif check.identifier == "ai.response":
            checks.extend(check.handler(result, "http://127.0.0.1:11434"))
        elif check.identifier == "context.report":
            checks.extend(check.handler(result))
    if artifact_type == "unsupported":
        checks.append(
            CheckResult(
                check_id="artifact.support",
                status="INCOMPLETE",
                required=True,
                reason="No verification checks exist for this execution artifact type",
            )
        )
    return ProofReport(
        artifact_type=artifact_type,
        overall_status=aggregate_status(checks),
        checks=checks,
    )
