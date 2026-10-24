"""Strict loopback endpoint validation for optional local AI calls."""

from urllib.parse import urlparse

from zeroagent.ai.models import ProviderError


def validate_endpoint(endpoint: str) -> str:
    """Allow only plain HTTP exact loopback Ollama root endpoints."""
    parsed = urlparse(endpoint)
    if parsed.scheme != "http":
        raise ProviderError("invalid_endpoint", "Ollama endpoint must use http")
    if parsed.username or parsed.password:
        raise ProviderError(
            "invalid_endpoint", "Ollama endpoint must not contain credentials"
        )
    if parsed.hostname not in {"127.0.0.1", "::1"}:
        raise ProviderError(
            "invalid_endpoint", "Ollama endpoint must use loopback host"
        )
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ProviderError(
            "invalid_endpoint",
            "Ollama endpoint must not include path, query, or fragment",
        )
    try:
        port = parsed.port
    except ValueError as error:
        raise ProviderError(
            "invalid_endpoint", "Ollama endpoint has invalid port"
        ) from error
    if port not in {None, 11434}:
        raise ProviderError("invalid_endpoint", "Ollama endpoint port must be 11434")
    host = "[::1]" if parsed.hostname == "::1" else parsed.hostname
    return f"http://{host}:11434"
