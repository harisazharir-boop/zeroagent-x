"""Typed, safe-by-default framework configuration."""

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    """Configuration for functionality available in this foundation release.

    Values deliberately disable network access, telemetry, cloud providers, and command
    execution. Later components must require explicit user configuration to relax them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    telemetry_enabled: bool = False
    network_enabled: bool = False
    cloud_providers_enabled: bool = False
    paid_api_providers_enabled: bool = False
    shell_command_execution_enabled: bool = False
    agent_execution_enabled: bool = False
    opencode_enabled: bool = False
    opencode_executable: str | None = None
    agent_execution_timeout_seconds: int = Field(default=60, ge=1, le=600)
    agent_execution_max_output_bytes: int = Field(
        default=64_000, ge=1_024, le=1_000_000
    )
    require_explicit_destructive_action_authorization: bool = True
    analysis_max_files: int = Field(default=10_000, ge=1)
    analysis_max_file_size_bytes: int = Field(default=5_000_000, ge=1)
    analysis_max_directory_depth: int = Field(default=20, ge=0)
    blackbox_storage_dir: str | None = None
    blackbox_max_records: int = Field(default=100, ge=1, le=10_000)
    blackbox_max_record_bytes: int = Field(default=1_000_000, ge=1_024)
    blackbox_max_record_age_days: int | None = Field(default=30, ge=1)
    local_ai_enabled: bool = False
    ollama_endpoint: str = "http://127.0.0.1:11434"
    ollama_timeout_seconds: int = Field(default=30, ge=1, le=120)
    ollama_max_prompt_chars: int = Field(default=8_000, ge=1, le=100_000)
    ollama_max_response_chars: int = Field(default=16_000, ge=1, le=100_000)
    workspace_root: str | None = Field(default=None)


def load_settings() -> Settings:
    """Return safe default settings without reading environment or network state."""
    return Settings()
