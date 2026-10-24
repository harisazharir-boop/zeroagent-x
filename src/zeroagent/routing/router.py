"""Deterministic local task classifier, capability registry, and policy router."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from zeroagent.config import Settings, load_settings
from zeroagent.core.diagnostics import collect_diagnostics
from zeroagent.core.repository import analyze_repository

TaskHandler = Callable[[Path | None], Any]
ExecutionObserver = Callable[[str, dict[str, object]], None]

REPOSITORY_ANALYSIS = "repository_analysis"
LANGUAGE_DETECTION = "language_detection"
DEPENDENCY_INSPECTION = "dependency_inspection"
ENVIRONMENT_DIAGNOSTICS = "environment_diagnostics"
LOCAL_AI = "local_ai"
UNKNOWN = "unknown"


class RoutingModel(BaseModel):
    """Strict base model for routing evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Classification(RoutingModel):
    category: str
    normalized_task: str
    reason: str


class CandidateEvaluation(RoutingModel):
    capability_id: str
    allowed: bool
    reason: str


class PolicySnapshot(RoutingModel):
    network_allowed: bool
    paid_api_allowed: bool
    cloud_provider_allowed: bool
    shell_allowed: bool
    telemetry_allowed: bool


class RoutingDecision(RoutingModel):
    task: str
    classification: Classification
    selected_capability: str | None
    decision: str
    reason: str
    policy: PolicySnapshot
    candidates: list[CandidateEvaluation]
    execution_performed: bool = False


class RoutingError(RuntimeError):
    """Raised when a request cannot safely route or execute."""


@dataclass(frozen=True)
class Capability:
    """Static declaration of one local capability and its explicit handler."""

    identifier: str
    description: str
    categories: frozenset[str]
    required_permissions: frozenset[str] = frozenset()
    requires_network: bool = False
    requires_paid_api: bool = False
    requires_shell: bool = False
    available: bool = True
    priority: int = 100
    requires_workspace: bool = False
    handler: TaskHandler | None = None


class CapabilityRegistry:
    """Small static registry. Runtime plugins and dynamic imports are unsupported."""

    def __init__(self, capabilities: list[Capability] | None = None) -> None:
        self._capabilities: dict[str, Capability] = {}
        for capability in capabilities or []:
            self.register(capability)

    def register(self, capability: Capability) -> None:
        if capability.identifier in self._capabilities:
            raise ValueError(
                f"Duplicate capability identifier: {capability.identifier}"
            )
        self._capabilities[capability.identifier] = capability

    def for_category(self, category: str) -> list[Capability]:
        return sorted(
            (
                capability
                for capability in self._capabilities.values()
                if category in capability.categories
            ),
            key=lambda capability: (capability.priority, capability.identifier),
        )


def classify_task(task: str) -> Classification:
    """Classify exact word tokens using specific-category precedence."""
    normalized = " ".join(task.casefold().split())
    tokens = set(re.findall(r"[a-z0-9_]+", normalized))
    if not normalized:
        return Classification(
            category=UNKNOWN, normalized_task=normalized, reason="Task is empty"
        )
    if tokens & {"dependency", "dependencies", "requirements", "packages"}:
        return Classification(
            category=DEPENDENCY_INSPECTION,
            normalized_task=normalized,
            reason="Matched dependency-related whole-word token",
        )
    if tokens & {"language", "languages"}:
        return Classification(
            category=LANGUAGE_DETECTION,
            normalized_task=normalized,
            reason="Matched language-related whole-word token",
        )
    if tokens & {"repository", "repo", "project"} and tokens & {
        "analyze",
        "analysis",
        "inspect",
        "scan",
    }:
        return Classification(
            category=REPOSITORY_ANALYSIS,
            normalized_task=normalized,
            reason="Matched repository and analysis whole-word tokens",
        )
    if tokens & {"environment", "diagnostics"} or {"check", "development"} <= tokens:
        return Classification(
            category=ENVIRONMENT_DIAGNOSTICS,
            normalized_task=normalized,
            reason="Matched environment diagnostics whole-word tokens",
        )
    return Classification(
        category=UNKNOWN,
        normalized_task=normalized,
        reason="No supported whole-word rule matched",
    )


def _analysis_handler(workspace: Path | None) -> Any:
    if workspace is None:
        raise RoutingError("Selected capability requires --workspace")
    return analyze_repository(workspace)


def _language_handler(workspace: Path | None) -> Any:
    report = _analysis_handler(workspace)
    return {
        "workspace_identifier": report.workspace_identifier,
        "languages": report.languages,
    }


def _dependency_handler(workspace: Path | None) -> Any:
    report = _analysis_handler(workspace)
    return {
        "workspace_identifier": report.workspace_identifier,
        "dependencies": report.dependencies,
    }


def _diagnostics_handler(workspace: Path | None) -> Any:
    del workspace
    return collect_diagnostics(load_settings())


def default_registry() -> CapabilityRegistry:
    """Create built-in local capability registry with no provider capabilities."""
    return CapabilityRegistry(
        [
            Capability(
                identifier="repository_analyzer",
                description="Read-only repository intelligence report.",
                categories=frozenset({REPOSITORY_ANALYSIS}),
                priority=10,
                requires_workspace=True,
                handler=_analysis_handler,
            ),
            Capability(
                identifier="language_statistics",
                description="Language file-count statistics from repository analysis.",
                categories=frozenset({LANGUAGE_DETECTION}),
                priority=10,
                requires_workspace=True,
                handler=_language_handler,
            ),
            Capability(
                identifier="dependency_inspector",
                description="Declared dependency metadata from repository manifests.",
                categories=frozenset({DEPENDENCY_INSPECTION}),
                priority=10,
                requires_workspace=True,
                handler=_dependency_handler,
            ),
            Capability(
                identifier="environment_diagnostics",
                description="Local Python and operating-system diagnostics.",
                categories=frozenset({ENVIRONMENT_DIAGNOSTICS}),
                priority=10,
                handler=_diagnostics_handler,
            ),
            Capability(
                identifier="local_ollama_text",
                description=(
                    "Explicit local Ollama text generation via dedicated AI commands."
                ),
                categories=frozenset({LOCAL_AI}),
                priority=100,
            ),
        ]
    )


def _policy_snapshot(settings: Settings) -> PolicySnapshot:
    return PolicySnapshot(
        network_allowed=settings.network_enabled,
        paid_api_allowed=settings.paid_api_providers_enabled,
        cloud_provider_allowed=settings.cloud_providers_enabled,
        shell_allowed=settings.shell_command_execution_enabled,
        telemetry_allowed=settings.telemetry_enabled,
    )


def _denial_reason(
    capability: Capability, settings: Settings, execution: bool
) -> str | None:
    if not capability.available:
        return "Capability is unavailable"
    if capability.requires_network and not settings.network_enabled:
        return "Network access is disabled by policy"
    if capability.requires_paid_api and not settings.paid_api_providers_enabled:
        return "Paid API access is disabled by policy"
    if capability.requires_shell and not settings.shell_command_execution_enabled:
        return "Shell execution is disabled by policy"
    if (
        "cloud_provider" in capability.required_permissions
        and not settings.cloud_providers_enabled
    ):
        return "Cloud provider access is disabled by policy"
    if execution and capability.handler is None:
        return "Capability has no execution handler"
    return None


def route_task(
    task: str,
    *,
    settings: Settings | None = None,
    registry: CapabilityRegistry | None = None,
    execution: bool = False,
) -> tuple[RoutingDecision, Capability | None]:
    """Classify and select first policy-permitted static capability."""
    active_settings = settings or load_settings()
    active_registry = registry or default_registry()
    classification = classify_task(task)
    policy = _policy_snapshot(active_settings)
    if classification.category == UNKNOWN:
        decision = RoutingDecision(
            task=task,
            classification=classification,
            selected_capability=None,
            decision="denied",
            reason="Task category is unsupported",
            policy=policy,
            candidates=[],
        )
        return decision, None
    evaluations: list[CandidateEvaluation] = []
    for capability in active_registry.for_category(classification.category):
        reason = _denial_reason(capability, active_settings, execution)
        evaluations.append(
            CandidateEvaluation(
                capability_id=capability.identifier,
                allowed=reason is None,
                reason=reason or "Registered local capability supports the task",
            )
        )
        if reason is None:
            decision = RoutingDecision(
                task=task,
                classification=classification,
                selected_capability=capability.identifier,
                decision="allowed",
                reason=(
                    "Registered local capability supports the task "
                    "and policy permits it"
                ),
                policy=policy,
                candidates=evaluations,
            )
            return decision, capability
    decision = RoutingDecision(
        task=task,
        classification=classification,
        selected_capability=None,
        decision="denied",
        reason="No registered capability is permitted for task category",
        policy=policy,
        candidates=evaluations,
    )
    return decision, None


def run_task(
    task: str,
    workspace: Path | None,
    *,
    settings: Settings | None = None,
    registry: CapabilityRegistry | None = None,
    observer: ExecutionObserver | None = None,
) -> tuple[RoutingDecision, Any]:
    """Route then execute only selected, policy-permitted static handler."""
    decision, capability = route_task(
        task, settings=settings, registry=registry, execution=True
    )
    if capability is None:
        raise RoutingError(decision.reason)
    if observer:
        observer(
            "task_classified",
            {"category": decision.classification.category},
        )
        observer("capability_selected", {"capability": capability.identifier})
        observer("policy_checked", {"decision": decision.decision})
    if capability.requires_workspace and workspace is None:
        raise RoutingError("Selected capability requires --workspace")
    if capability.handler is None:
        raise RoutingError("Selected capability has no execution handler")
    if observer:
        observer("capability_started", {"capability": capability.identifier})
    try:
        result = capability.handler(workspace)
    except Exception:
        if observer:
            observer("execution_failed", {"capability": capability.identifier})
        raise
    if observer:
        observer("capability_completed", {"capability": capability.identifier})
    return decision.model_copy(update={"execution_performed": True}), result
