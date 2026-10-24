"""Honest structural verification boundary for local AI metadata."""

from zeroagent.ai.models import GenerationResponse
from zeroagent.proof.models import CheckResult


def verify_ai_response(
    response: GenerationResponse, endpoint: str
) -> list[CheckResult]:
    """Verify metadata only; generated text semantics remain unverified."""
    metadata = CheckResult(
        check_id="ai.metadata",
        status="PASS"
        if response.model and endpoint.startswith("http://127.0.0.1:")
        else "FAIL",
        required=True,
        reason=(
            "Local provider metadata and selected model are present"
            if response.model and endpoint.startswith("http://127.0.0.1:")
            else "Local provider metadata is inconsistent"
        ),
    )
    semantics = CheckResult(
        check_id="ai.semantic_correctness",
        status="INCOMPLETE",
        required=True,
        reason="Generated text accuracy and safety are not verified by ProofEngine",
    )
    return [metadata, semantics]
