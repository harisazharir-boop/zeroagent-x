"""Deterministic evidence-based verification for local execution artifacts."""

from zeroagent.proof.engine import verify_execution
from zeroagent.proof.models import ProofReport

__all__ = ["ProofReport", "verify_execution"]
