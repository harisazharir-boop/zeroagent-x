"""Explicit deterministic adapter registry. Dynamic plugins are unsupported."""

from __future__ import annotations

from zeroagent.execution.adapters import AgentAdapter


class AdapterRegistry:
    def __init__(self, adapters: list[AgentAdapter] | None = None) -> None:
        self._adapters: dict[str, AgentAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: AgentAdapter) -> None:
        if not adapter.identifier or adapter.identifier in self._adapters:
            raise ValueError(f"Duplicate adapter identifier: {adapter.identifier}")
        self._adapters[adapter.identifier] = adapter

    def get(self, identifier: str) -> AgentAdapter:
        try:
            return self._adapters[identifier]
        except KeyError as error:
            raise ValueError(f"Unknown adapter: {identifier}") from error

    def identifiers(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))
