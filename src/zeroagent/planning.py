"""Deterministic, planning-only tool registry and task planner."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from zeroagent.security.workspace import validate_workspace


class PlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolDescriptor(PlanningModel):
    identifier: str
    name: str
    description: str
    permissions: list[str]
    side_effects: str
    implementation_status: str
    requires_approval: bool = False


class PlanStep(PlanningModel):
    identifier: str
    description: str
    tool: str
    depends_on: list[str] = []
    permissions: list[str]
    availability: str


class TaskPlan(PlanningModel):
    schema_version: str = "1"
    task: str = Field(min_length=1, max_length=4_000)
    workspace_identifier: str
    status: str
    steps: list[PlanStep] = Field(max_length=20)
    execution_performed: bool = False


class PlanError(ValueError):
    """Invalid or unsafe planning input."""


class ToolRegistry:
    def __init__(self, tools: list[ToolDescriptor] | None = None) -> None:
        self._tools: dict[str, ToolDescriptor] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ToolDescriptor) -> None:
        if tool.identifier in self._tools:
            raise PlanError(f"Duplicate tool identifier: {tool.identifier}")
        self._tools[tool.identifier] = tool

    def get(self, identifier: str) -> ToolDescriptor:
        try:
            return self._tools[identifier]
        except KeyError as error:
            raise PlanError(f"Unknown tool identifier: {identifier}") from error

    def all(self) -> list[ToolDescriptor]:
        return [self._tools[key] for key in sorted(self._tools)]


def default_registry() -> ToolRegistry:
    implemented = "IMPLEMENTED"
    future = "NOT_IMPLEMENTED"
    return ToolRegistry(
        [
            ToolDescriptor(
                identifier="repository.analyze",
                name="Analyze Repository",
                description="Inspect bounded repository metadata.",
                permissions=["metadata_read"],
                side_effects="none",
                implementation_status=implemented,
            ),
            ToolDescriptor(
                identifier="context.inspect",
                name="Inspect Context",
                description="Discover safe context metadata.",
                permissions=["metadata_read"],
                side_effects="none",
                implementation_status=implemented,
            ),
            ToolDescriptor(
                identifier="context.select",
                name="Select Context",
                description="Select safe paths deterministically.",
                permissions=["metadata_read"],
                side_effects="none",
                implementation_status=implemented,
            ),
            ToolDescriptor(
                identifier="context.read",
                name="Read Context",
                description="Read authorized bounded source excerpts.",
                permissions=["source_read"],
                side_effects="none",
                implementation_status=implemented,
                requires_approval=True,
            ),
            ToolDescriptor(
                identifier="ai.local_ask",
                name="Local AI Ask",
                description="Send explicit text to local Ollama.",
                permissions=["local_ai_request"],
                side_effects="local_loopback",
                implementation_status=implemented,
                requires_approval=True,
            ),
            ToolDescriptor(
                identifier="proof.verify",
                name="Verify Evidence",
                description="Verify structural evidence.",
                permissions=["evidence_read"],
                side_effects="none",
                implementation_status=implemented,
            ),
            ToolDescriptor(
                identifier="history.list",
                name="List History",
                description="Read local BlackBox history.",
                permissions=["history_read"],
                side_effects="none",
                implementation_status=implemented,
            ),
            ToolDescriptor(
                identifier="history.inspect",
                name="Inspect History",
                description="Read stored execution record.",
                permissions=["history_read"],
                side_effects="none",
                implementation_status=implemented,
            ),
            ToolDescriptor(
                identifier="history.replay",
                name="Replay History",
                description="Display historical record only.",
                permissions=["history_read"],
                side_effects="none",
                implementation_status=implemented,
            ),
            ToolDescriptor(
                identifier="code.patch",
                name="Propose Patch",
                description="Validate structured text-only patch proposal.",
                permissions=["code_write"],
                side_effects="workspace_write",
                implementation_status=implemented,
                requires_approval=True,
            ),
            ToolDescriptor(
                identifier="code.apply",
                name="Apply Changes",
                description="Apply exact approved text-only patch.",
                permissions=["code_write"],
                side_effects="workspace_write",
                implementation_status=implemented,
                requires_approval=True,
            ),
            ToolDescriptor(
                identifier="tests.execute",
                name="Run Tests",
                description="Controlled allowlisted test execution.",
                permissions=["process_execute"],
                side_effects="process",
                implementation_status=implemented,
                requires_approval=True,
            ),
            ToolDescriptor(
                identifier="workspace.write",
                name="Write Workspace",
                description="Future workspace write capability.",
                permissions=["code_write"],
                side_effects="workspace_write",
                implementation_status=future,
                requires_approval=True,
            ),
        ]
    )


def _step(
    index: int,
    description: str,
    tool: str,
    dependencies: list[str],
    registry: ToolRegistry,
) -> PlanStep:
    descriptor = registry.get(tool)
    availability = descriptor.implementation_status
    if descriptor.requires_approval and availability == "IMPLEMENTED":
        availability = "REQUIRES_AUTHORIZATION"
    return PlanStep(
        identifier=f"step-{index:03}",
        description=description,
        tool=tool,
        depends_on=dependencies,
        permissions=descriptor.permissions,
        availability=availability,
    )


def create_plan(
    task: str, workspace: Path, registry: ToolRegistry | None = None
) -> TaskPlan:
    """Create deterministic offline plan; never invokes tool handlers."""
    if not task.strip() or len(task) > 4_000:
        raise PlanError("Task must contain 1 to 4000 characters")
    root = validate_workspace(workspace)
    active = registry or default_registry()
    terms = task.casefold()
    steps = [_step(1, "Analyze repository structure", "repository.analyze", [], active)]
    if any(
        term in terms
        for term in (
            "architecture",
            "explain",
            "authentication",
            "bug",
            "feature",
            "refactor",
        )
    ):
        steps.append(
            _step(
                2,
                "Select relevant repository context",
                "context.select",
                ["step-001"],
                active,
            )
        )
        steps.append(
            _step(
                3, "Read approved source excerpts", "context.read", ["step-002"], active
            )
        )
    if any(
        term in terms
        for term in ("bug", "investigate", "explain", "architecture", "authentication")
    ):
        steps.append(
            _step(
                len(steps) + 1,
                "Request local reasoning from explicit model",
                "ai.local_ask",
                [steps[-1].identifier],
                active,
            )
        )
    if any(term in terms for term in ("fix", "feature", "refactor", "implement")):
        steps.append(
            _step(
                len(steps) + 1,
                "Propose code changes",
                "code.patch",
                [steps[-1].identifier],
                active,
            )
        )
        steps.append(
            _step(
                len(steps) + 1,
                "Apply approved changes",
                "code.apply",
                [steps[-1].identifier],
                active,
            )
        )
    if any(term in terms for term in ("test", "verify", "bug", "fix")):
        steps.append(
            _step(
                len(steps) + 1,
                "Run targeted tests",
                "tests.execute",
                [steps[-1].identifier],
                active,
            )
        )
        steps.append(
            _step(
                len(steps) + 1,
                "Verify available evidence",
                "proof.verify",
                [steps[-1].identifier],
                active,
            )
        )
    status = (
        "INCOMPLETE"
        if any(step.availability == "NOT_IMPLEMENTED" for step in steps)
        else (
            "REQUIRES_AUTHORIZATION"
            if any(step.availability == "REQUIRES_AUTHORIZATION" for step in steps)
            else "READY"
        )
    )
    return TaskPlan(
        task=task, workspace_identifier=root.name, status=status, steps=steps
    )


def validate_plan(plan: TaskPlan, registry: ToolRegistry | None = None) -> TaskPlan:
    """Reject unsafe tools, permissions, dependencies, and execution claims."""
    active = registry or default_registry()
    if plan.execution_performed:
        raise PlanError("Planning-only plans must not claim execution")
    identifiers = [step.identifier for step in plan.steps]
    if len(identifiers) != len(set(identifiers)):
        raise PlanError("Plan step identifiers must be unique")
    known = set(identifiers)
    for step in plan.steps:
        descriptor = active.get(step.tool)
        if step.permissions != descriptor.permissions:
            raise PlanError(f"Permission mismatch for {step.tool}")
        if any(dependency not in known for dependency in step.depends_on):
            raise PlanError(f"Missing dependency for {step.identifier}")
    graph = {step.identifier: set(step.depends_on) for step in plan.steps}
    visited: set[str] = set()
    active_nodes: set[str] = set()

    def visit(node: str) -> None:
        if node in active_nodes:
            raise PlanError("Plan dependencies contain a cycle")
        if node not in visited:
            active_nodes.add(node)
            for dependency in graph[node]:
                visit(dependency)
            active_nodes.remove(node)
            visited.add(node)

    for identifier in identifiers:
        visit(identifier)
    return plan


def load_plan(path: Path) -> TaskPlan:
    """Load bounded JSON plan as untrusted data without evaluating content."""
    if path.is_symlink() or path.stat().st_size > 256_000:
        raise PlanError("Plan file is unsafe or exceeds size limit")
    try:
        return TaskPlan.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise PlanError("Plan file is not valid planning JSON") from error
