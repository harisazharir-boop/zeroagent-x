"""Typed untrusted local-provider request and response models."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderInfo(AIModel):
    provider_id: str = "ollama"
    endpoint: str
    reachable: bool
    model_count: int | None = None
    error_category: str | None = None
    error_message: str | None = None


class InstalledModel(AIModel):
    identifier: str
    size_bytes: int | None = None
    modified_at: str | None = None


class GenerationRequest(AIModel):
    model: str = Field(min_length=1, max_length=256)
    prompt: str = Field(min_length=1)

    @field_validator("model")
    @classmethod
    def validate_model_identifier(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value):
            raise ValueError("Model identifier contains unsupported characters")
        return value


class GenerationResponse(AIModel):
    provider_id: str = "ollama"
    model: str
    response: str
    total_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


class ProviderError(RuntimeError):
    """Actionable local provider failure with no remote fallback."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(message)
