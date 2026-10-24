"""Tests for planning-only typed tool registry and validator."""

from pathlib import Path

import pytest

from zeroagent.planning import (
    PlanError,
    PlanStep,
    TaskPlan,
    create_plan,
    default_registry,
    validate_plan,
)


def test_registry_future_tools_remain_nonimplemented() -> None:
    registry = default_registry()
    assert registry.get("repository.analyze").implementation_status == "IMPLEMENTED"
    assert registry.get("code.apply").implementation_status == "IMPLEMENTED"
    with pytest.raises(PlanError, match="Unknown"):
        registry.get("shell.execute")


def test_planner_is_deterministic_and_never_executes(tmp_path: Path) -> None:
    first = create_plan("Find and fix authentication bug", tmp_path)
    second = create_plan("Find and fix authentication bug", tmp_path)
    assert first == second
    assert first.execution_performed is False
    assert first.status == "INCOMPLETE"
    assert any(step.tool == "code.patch" for step in first.steps)


def test_validator_rejects_permission_and_cycle_changes(tmp_path: Path) -> None:
    plan = create_plan("Explain architecture", tmp_path)
    altered = plan.model_copy(
        update={
            "steps": [plan.steps[0].model_copy(update={"permissions": ["code_write"]})]
        }
    )
    with pytest.raises(PlanError, match="Permission mismatch"):
        validate_plan(altered)
    cyclic = TaskPlan(
        task="x",
        workspace_identifier="x",
        status="READY",
        steps=[
            PlanStep(
                identifier="step-001",
                description="x",
                tool="repository.analyze",
                depends_on=["step-001"],
                permissions=["metadata_read"],
                availability="IMPLEMENTED",
            )
        ],
    )
    with pytest.raises(PlanError, match="cycle"):
        validate_plan(cyclic)
