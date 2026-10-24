"""Tests for deterministic local task routing."""

from pathlib import Path

import pytest

from zeroagent.config import Settings
from zeroagent.routing.router import (
    DEPENDENCY_INSPECTION,
    ENVIRONMENT_DIAGNOSTICS,
    LANGUAGE_DETECTION,
    REPOSITORY_ANALYSIS,
    UNKNOWN,
    Capability,
    CapabilityRegistry,
    RoutingError,
    classify_task,
    default_registry,
    route_task,
    run_task,
)


@pytest.mark.parametrize(
    ("task", "category"),
    [
        ("Analyze this repository", REPOSITORY_ANALYSIS),
        ("Detect programming languages", LANGUAGE_DETECTION),
        ("Show project dependencies", DEPENDENCY_INSPECTION),
        ("Check my development environment", ENVIRONMENT_DIAGNOSTICS),
        ("ANALYZE THIS REPOSITORY", REPOSITORY_ANALYSIS),
        ("", UNKNOWN),
        ("deploy the application", UNKNOWN),
        ("languageology", UNKNOWN),
    ],
)
def test_classification_rules(task: str, category: str) -> None:
    classification = classify_task(task)
    assert classification.category == category
    assert classification.reason


def test_classification_precedence_is_deterministic() -> None:
    classification = classify_task("Analyze repository dependencies and languages")
    assert classification.category == DEPENDENCY_INSPECTION


def test_registry_rejects_duplicate_identifier() -> None:
    registry = CapabilityRegistry()
    capability = Capability("duplicate", "test", frozenset({REPOSITORY_ANALYSIS}))
    registry.register(capability)
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(capability)


def test_registry_ordering_is_priority_then_identifier() -> None:
    registry = CapabilityRegistry(
        [
            Capability("zeta", "test", frozenset({REPOSITORY_ANALYSIS}), priority=10),
            Capability("alpha", "test", frozenset({REPOSITORY_ANALYSIS}), priority=10),
            Capability("first", "test", frozenset({REPOSITORY_ANALYSIS}), priority=1),
        ]
    )
    assert [item.identifier for item in registry.for_category(REPOSITORY_ANALYSIS)] == [
        "first",
        "alpha",
        "zeta",
    ]


@pytest.mark.parametrize(
    ("capability", "settings", "reason"),
    [
        (
            Capability(
                "network",
                "test",
                frozenset({REPOSITORY_ANALYSIS}),
                requires_network=True,
            ),
            Settings(),
            "Network access",
        ),
        (
            Capability(
                "paid", "test", frozenset({REPOSITORY_ANALYSIS}), requires_paid_api=True
            ),
            Settings(),
            "Paid API",
        ),
        (
            Capability(
                "shell", "test", frozenset({REPOSITORY_ANALYSIS}), requires_shell=True
            ),
            Settings(),
            "Shell execution",
        ),
        (
            Capability(
                "offline", "test", frozenset({REPOSITORY_ANALYSIS}), available=False
            ),
            Settings(),
            "unavailable",
        ),
    ],
)
def test_policy_denies_restricted_or_unavailable_capability(
    capability: Capability, settings: Settings, reason: str
) -> None:
    decision, selected = route_task(
        "Analyze this repository",
        settings=settings,
        registry=CapabilityRegistry([capability]),
    )
    assert selected is None
    assert decision.decision == "denied"
    assert reason in decision.candidates[0].reason


def test_policy_allows_registered_safe_capability_without_execution() -> None:
    called = False

    def handler(workspace: Path | None) -> str:
        nonlocal called
        called = True
        return "ran"

    registry = CapabilityRegistry(
        [Capability("safe", "test", frozenset({REPOSITORY_ANALYSIS}), handler=handler)]
    )
    decision, selected = route_task(
        "Analyze this repository", registry=registry, execution=False
    )
    assert decision.decision == "allowed"
    assert selected is not None
    assert called is False


def test_denied_handler_never_executes() -> None:
    called = False

    def handler(workspace: Path | None) -> str:
        nonlocal called
        called = True
        return "ran"

    registry = CapabilityRegistry(
        [
            Capability(
                "blocked",
                "test",
                frozenset({REPOSITORY_ANALYSIS}),
                requires_network=True,
                handler=handler,
            )
        ]
    )
    with pytest.raises(RoutingError):
        run_task("Analyze this repository", Path("."), registry=registry)
    assert called is False


def test_run_executes_real_repository_handler(tmp_path: Path) -> None:
    (tmp_path / "sample.py").write_text("pass\n")
    decision, result = run_task("Analyze this repository", tmp_path)
    assert decision.execution_performed is True
    assert decision.selected_capability == "repository_analyzer"
    assert result.file_count == 1


def test_run_unknown_task_fails_safely() -> None:
    with pytest.raises(RoutingError, match="unsupported"):
        run_task("Deploy this application", None)


def test_default_registry_has_expected_local_capabilities() -> None:
    registry = default_registry()
    assert (
        registry.for_category(REPOSITORY_ANALYSIS)[0].identifier
        == "repository_analyzer"
    )
    assert (
        registry.for_category(LANGUAGE_DETECTION)[0].identifier == "language_statistics"
    )
