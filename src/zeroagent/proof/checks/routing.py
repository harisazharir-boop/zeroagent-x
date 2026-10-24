"""Independent checks for recorded routing decisions."""

from zeroagent.config import Settings
from zeroagent.proof.models import CheckResult
from zeroagent.routing.router import CapabilityRegistry, RoutingDecision


def verify_routing(
    decision: RoutingDecision,
    registry: CapabilityRegistry,
    settings: Settings,
) -> CheckResult:
    """Validate selected capability and policy against current static registry."""
    if decision.decision == "denied":
        if decision.execution_performed:
            return CheckResult(
                check_id="routing.decision",
                status="FAIL",
                required=True,
                reason="Denied routing decision is marked as executed",
            )
        return CheckResult(
            check_id="routing.decision",
            status="PASS",
            required=True,
            reason="Denied routing decision was not executed",
        )
    if decision.decision != "allowed" or not decision.selected_capability:
        return CheckResult(
            check_id="routing.decision",
            status="FAIL",
            required=True,
            reason="Allowed routing decision has no selected capability",
        )
    capabilities = registry.for_category(decision.classification.category)
    capability = next(
        (
            item
            for item in capabilities
            if item.identifier == decision.selected_capability
        ),
        None,
    )
    if capability is None:
        return CheckResult(
            check_id="routing.decision",
            status="FAIL",
            required=True,
            reason="Selected capability is not registered for classified category",
        )
    if not capability.available:
        return CheckResult(
            check_id="routing.decision",
            status="FAIL",
            required=True,
            reason="Selected capability is unavailable",
        )
    if capability.requires_network and not settings.network_enabled:
        return CheckResult(
            check_id="routing.decision",
            status="FAIL",
            required=True,
            reason="Selected capability requires disabled network access",
        )
    if capability.requires_paid_api and not settings.paid_api_providers_enabled:
        return CheckResult(
            check_id="routing.decision",
            status="FAIL",
            required=True,
            reason="Selected capability requires disabled paid API access",
        )
    if capability.requires_shell and not settings.shell_command_execution_enabled:
        return CheckResult(
            check_id="routing.decision",
            status="FAIL",
            required=True,
            reason="Selected capability requires disabled shell execution",
        )
    if (
        "cloud_provider" in capability.required_permissions
        and not settings.cloud_providers_enabled
    ):
        return CheckResult(
            check_id="routing.decision",
            status="FAIL",
            required=True,
            reason="Selected capability requires disabled cloud provider access",
        )
    if decision.execution_performed and capability.handler is None:
        return CheckResult(
            check_id="routing.decision",
            status="FAIL",
            required=True,
            reason="Recorded execution has no registered handler",
        )
    return CheckResult(
        check_id="routing.decision",
        status="PASS",
        required=True,
        reason="Selected capability is registered, available, and policy-permitted",
    )
