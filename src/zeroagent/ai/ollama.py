"""Small local-only Ollama HTTP API client using Python standard library."""

from __future__ import annotations

import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from zeroagent.ai.models import (
    GenerationRequest,
    GenerationResponse,
    InstalledModel,
    ProviderError,
    ProviderInfo,
)
from zeroagent.ai.safety import validate_endpoint


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        return None


class OllamaClient:
    """Validated local Ollama client. Proxies and redirects are always disabled."""

    def __init__(
        self, endpoint: str, timeout_seconds: int, max_response_chars: int
    ) -> None:
        self.endpoint = validate_endpoint(endpoint)
        self.timeout_seconds = timeout_seconds
        self.max_response_chars = max_response_chars
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _request(self, path: str, payload: dict[str, object] | None = None) -> object:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.endpoint}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method="POST" if data else "GET",
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_chars * 4 + 4096)
        except HTTPError as error:
            raise ProviderError(
                "http_error", f"Ollama returned HTTP {error.code}"
            ) from error
        except TimeoutError as error:
            raise ProviderError("timeout", "Ollama request timed out") from error
        except URLError as error:
            if isinstance(error.reason, socket.timeout):
                raise ProviderError("timeout", "Ollama request timed out") from error
            raise ProviderError(
                "unreachable", "Ollama service is unreachable"
            ) from error
        if len(raw) > self.max_response_chars * 4:
            raise ProviderError(
                "response_too_large", "Ollama response exceeds size limit"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ProviderError(
                "invalid_response", "Ollama returned invalid JSON"
            ) from error

    def models(self) -> list[InstalledModel]:
        payload = self._request("/api/tags")
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise ProviderError(
                "invalid_response", "Ollama model list has invalid schema"
            )
        models: list[InstalledModel] = []
        for item in payload["models"]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ProviderError(
                    "invalid_response", "Ollama model metadata has invalid schema"
                )
            models.append(
                InstalledModel(
                    identifier=item["name"],
                    size_bytes=item.get("size")
                    if isinstance(item.get("size"), int)
                    else None,
                    modified_at=item.get("modified_at")
                    if isinstance(item.get("modified_at"), str)
                    else None,
                )
            )
        return sorted(models, key=lambda model: model.identifier)

    def doctor(self) -> ProviderInfo:
        try:
            models = self.models()
        except ProviderError as error:
            return ProviderInfo(
                endpoint=self.endpoint,
                reachable=False,
                error_category=error.category,
                error_message=str(error),
            )
        return ProviderInfo(
            endpoint=self.endpoint, reachable=True, model_count=len(models)
        )

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        if request.model not in {model.identifier for model in self.models()}:
            raise ProviderError(
                "missing_model", "Requested Ollama model is not installed"
            )
        payload = self._request(
            "/api/generate",
            {"model": request.model, "prompt": request.prompt, "stream": False},
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("response"), str
        ):
            raise ProviderError(
                "invalid_response", "Ollama generation response has invalid schema"
            )
        response = payload["response"]
        if len(response) > self.max_response_chars:
            raise ProviderError(
                "response_too_large", "Ollama generated response exceeds size limit"
            )
        return GenerationResponse(
            model=request.model,
            response=response,
            total_duration_ns=payload.get("total_duration")
            if isinstance(payload.get("total_duration"), int)
            else None,
            prompt_eval_count=payload.get("prompt_eval_count")
            if isinstance(payload.get("prompt_eval_count"), int)
            else None,
            eval_count=payload.get("eval_count")
            if isinstance(payload.get("eval_count"), int)
            else None,
        )
