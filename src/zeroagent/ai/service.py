"""Explicitly authorized local AI service facade."""

from zeroagent.ai.models import (
    GenerationRequest,
    GenerationResponse,
    InstalledModel,
    ProviderInfo,
)
from zeroagent.ai.ollama import OllamaClient
from zeroagent.config import Settings


class LocalAIService:
    """Creates local-only client only for dedicated AI command interactions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OllamaClient(
            settings.ollama_endpoint,
            settings.ollama_timeout_seconds,
            settings.ollama_max_response_chars,
        )

    def doctor(self) -> ProviderInfo:
        return self.client.doctor()

    def models(self) -> list[InstalledModel]:
        return self.client.models()

    def ask(self, prompt: str, model: str) -> GenerationResponse:
        if len(prompt) > self.settings.ollama_max_prompt_chars:
            raise ValueError("Prompt exceeds configured size limit")
        return self.client.generate(GenerationRequest(model=model, prompt=prompt))
