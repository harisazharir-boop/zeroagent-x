"""Static ProofEngine check registry."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class VerificationCheck:
    identifier: str
    artifact_types: frozenset[str]
    handler: Callable[..., object]


class VerificationRegistry:
    """Explicit check registry. Plugins and dynamic imports are unsupported."""

    def __init__(self, checks: list[VerificationCheck] | None = None) -> None:
        self._checks: dict[str, VerificationCheck] = {}
        for check in checks or []:
            self.register(check)

    def register(self, check: VerificationCheck) -> None:
        if check.identifier in self._checks:
            raise ValueError(
                f"Duplicate verification check identifier: {check.identifier}"
            )
        self._checks[check.identifier] = check

    def for_artifact(self, artifact_type: str) -> list[VerificationCheck]:
        return sorted(
            (
                check
                for check in self._checks.values()
                if artifact_type in check.artifact_types
            ),
            key=lambda check: check.identifier,
        )

    def get(self, identifier: str) -> VerificationCheck:
        """Return registered check or fail closed for unknown identifiers."""
        try:
            return self._checks[identifier]
        except KeyError as error:
            raise KeyError(
                f"Unknown verification check identifier: {identifier}"
            ) from error
