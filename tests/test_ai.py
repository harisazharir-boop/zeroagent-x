"""Offline tests for optional loopback-only Ollama integration."""

import json
from urllib.error import URLError

import pytest
from typer.testing import CliRunner

from zeroagent.ai.models import (
    GenerationRequest,
    GenerationResponse,
    InstalledModel,
    ProviderError,
    ProviderInfo,
)
from zeroagent.ai.ollama import OllamaClient
from zeroagent.ai.safety import validate_endpoint
from zeroagent.ai.service import LocalAIService
from zeroagent.cli import app
from zeroagent.config import Settings
from zeroagent.proof.checks.ai import verify_ai_response
from zeroagent.routing.router import LOCAL_AI, REPOSITORY_ANALYSIS, default_registry

runner = CliRunner()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1:11434",
        "http://localhost:11434",
        "http://192.168.1.2:11434",
        "http://example.com:11434",
        "http://user:pass@127.0.0.1:11434",
        "http://127.0.0.1:9999",
        "http://127.0.0.1:11434/api/tags",
        "http://127.0.0.1:11434#fragment",
    ],
)
def test_endpoint_security_rejects_non_loopback_or_unexpected_urls(
    endpoint: str,
) -> None:
    with pytest.raises(ProviderError, match="Ollama endpoint"):
        validate_endpoint(endpoint)


def test_endpoint_security_accepts_default_loopback() -> None:
    assert validate_endpoint("http://127.0.0.1:11434") == "http://127.0.0.1:11434"


def test_ollama_models_and_generation_parse_realistic_responses(monkeypatch) -> None:
    client = OllamaClient("http://127.0.0.1:11434", 5, 100)

    def request(path: str, payload: dict[str, object] | None = None) -> object:
        if path == "/api/tags":
            return {"models": [{"name": "tiny", "size": 123}]}
        assert payload == {"model": "tiny", "prompt": "hello", "stream": False}
        return {"response": "world", "eval_count": 2}

    monkeypatch.setattr(client, "_request", request)
    assert client.models()[0].identifier == "tiny"
    response = client.generate(GenerationRequest(model="tiny", prompt="hello"))
    assert response.response == "world"
    assert response.eval_count == 2


@pytest.mark.parametrize(
    "payload",
    [{}, {"models": [{}]}, {"models": "not-a-list"}],
)
def test_invalid_provider_responses_fail_closed(monkeypatch, payload: object) -> None:
    client = OllamaClient("http://127.0.0.1:11434", 5, 100)
    monkeypatch.setattr(client, "_request", lambda path, request=None: payload)
    with pytest.raises(ProviderError, match="invalid schema"):
        client.models()


def test_missing_model_and_oversized_generation_fail(monkeypatch) -> None:
    client = OllamaClient("http://127.0.0.1:11434", 5, 3)
    monkeypatch.setattr(client, "models", lambda: [])
    with pytest.raises(ProviderError, match="not installed"):
        client.generate(GenerationRequest(model="missing", prompt="hello"))
    monkeypatch.setattr(client, "models", lambda: [InstalledModel(identifier="tiny")])
    monkeypatch.setattr(
        client, "_request", lambda path, payload=None: {"response": "large"}
    )
    with pytest.raises(ProviderError, match="size limit"):
        client.generate(GenerationRequest(model="tiny", prompt="hello"))


def test_prompt_limit_and_deterministic_router_priority() -> None:
    service = LocalAIService(Settings(ollama_max_prompt_chars=3))
    with pytest.raises(ValueError, match="size limit"):
        service.ask("four", "tiny")
    registry = default_registry()
    assert (
        registry.for_category(REPOSITORY_ANALYSIS)[0].identifier
        == "repository_analyzer"
    )
    assert registry.for_category(LOCAL_AI)[0].identifier == "local_ollama_text"


def test_ai_cli_commands_use_mocked_local_service(monkeypatch) -> None:
    class Service:
        def doctor(self) -> ProviderInfo:
            return ProviderInfo(
                endpoint="http://127.0.0.1:11434", reachable=True, model_count=1
            )

        def models(self):
            return [InstalledModel(identifier="tiny", size_bytes=123)]

        def ask(self, prompt: str, model: str) -> GenerationResponse:
            assert prompt == "hello"
            assert model == "tiny"
            return GenerationResponse(model=model, response="world")

    monkeypatch.setattr("zeroagent.cli._ai_service", lambda: Service())
    doctor = runner.invoke(app, ["ai", "doctor", "--format", "json"])
    models = runner.invoke(app, ["ai", "models", "--format", "json"])
    ask = runner.invoke(
        app, ["ai", "ask", "hello", "--model", "tiny", "--format", "json"]
    )
    assert json.loads(doctor.output)["reachable"] is True
    assert json.loads(models.output)[0]["identifier"] == "tiny"
    assert json.loads(ask.output)["response"] == "world"


def test_ai_cli_provider_failure_has_nonzero_exit(monkeypatch) -> None:
    class Service:
        def models(self):
            raise ProviderError("unreachable", "Ollama service is unreachable")

    monkeypatch.setattr("zeroagent.cli._ai_service", lambda: Service())
    result = runner.invoke(app, ["ai", "models"])
    assert result.exit_code == 2
    assert "unreachable" in result.output


def test_ai_proof_does_not_verify_generated_text_semantics() -> None:
    checks = verify_ai_response(
        GenerationResponse(model="tiny", response="untrusted output"),
        "http://127.0.0.1:11434",
    )
    assert checks[0].status == "PASS"
    assert checks[1].status == "INCOMPLETE"


def test_provider_normalizes_socket_timeout(monkeypatch) -> None:
    client = OllamaClient("http://127.0.0.1:11434", 5, 100)

    class Opener:
        def open(self, request, timeout):
            raise URLError(TimeoutError())

    monkeypatch.setattr(client, "_opener", Opener())
    with pytest.raises(ProviderError, match="timed out") as error:
        client.models()
    assert error.value.category == "timeout"
