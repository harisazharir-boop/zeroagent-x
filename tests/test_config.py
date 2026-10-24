"""Tests for safe configuration defaults."""

import pytest
from pydantic import ValidationError

from zeroagent.config import Settings, load_settings


def test_default_settings_disable_external_and_execution_features() -> None:
    settings = load_settings()

    assert settings.telemetry_enabled is False
    assert settings.network_enabled is False
    assert settings.cloud_providers_enabled is False
    assert settings.paid_api_providers_enabled is False
    assert settings.shell_command_execution_enabled is False
    assert settings.require_explicit_destructive_action_authorization is True


def test_settings_reject_unknown_options() -> None:
    with pytest.raises(ValidationError):
        Settings(unknown_option=True)
