"""Unit tests for the provider configuration and registry."""

from __future__ import annotations

import pytest

from beddel.adapters.litellm import LiteLLMAdapter
from beddel.adapters.provider_config import ProviderConfig, ProviderRegistry
from beddel.domain.models import ConfigurationError, ErrorCode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ProviderRegistry:
    """Fresh ProviderRegistry with built-in defaults."""
    return ProviderRegistry()


# ---------------------------------------------------------------------------
# 4.2 ProviderConfig model creation
# ---------------------------------------------------------------------------


def test_provider_config_all_fields() -> None:
    """ProviderConfig with all fields explicitly set stores each value."""
    # Arrange & Act
    config = ProviderConfig(
        provider="custom",
        api_key="sk-test-key",
        api_base="https://api.custom.com/v1",
        model_prefix="custom/",
        extra_params={"region": "us-east-1", "timeout": 30},
    )

    # Assert
    assert config.provider == "custom"
    assert config.api_key == "sk-test-key"
    assert config.api_base == "https://api.custom.com/v1"
    assert config.model_prefix == "custom/"
    assert config.extra_params == {"region": "us-east-1", "timeout": 30}


def test_provider_config_defaults() -> None:
    """ProviderConfig with only required field uses correct defaults."""
    # Arrange & Act
    config = ProviderConfig(provider="minimal")

    # Assert
    assert config.provider == "minimal"
    assert config.api_key is None
    assert config.api_base is None
    assert config.model_prefix == ""
    assert config.extra_params == {}


# ---------------------------------------------------------------------------
# 4.3 Built-in defaults (AC: 7)
# ---------------------------------------------------------------------------


def test_registry_builtin_openrouter(registry: ProviderRegistry) -> None:
    """Registry has openrouter with prefix 'openrouter/' and api_base."""
    # Act
    config = registry.get("openrouter")

    # Assert
    assert config.provider == "openrouter"
    assert config.model_prefix == "openrouter/"
    assert config.api_base == "https://openrouter.ai/api/v1"


def test_registry_builtin_gemini(registry: ProviderRegistry) -> None:
    """Registry has gemini with prefix 'gemini/'."""
    # Act
    config = registry.get("gemini")

    # Assert
    assert config.provider == "gemini"
    assert config.model_prefix == "gemini/"


def test_registry_builtin_bedrock(registry: ProviderRegistry) -> None:
    """Registry has bedrock with prefix 'bedrock/'."""
    # Act
    config = registry.get("bedrock")

    # Assert
    assert config.provider == "bedrock"
    assert config.model_prefix == "bedrock/"


# ---------------------------------------------------------------------------
# 4.4 register() and get() (AC: 3)
# ---------------------------------------------------------------------------


def test_registry_register_and_get(registry: ProviderRegistry) -> None:
    """register() adds a new provider, get() retrieves it."""
    # Arrange
    config = ProviderConfig(
        provider="azure",
        api_key="az-key-123",
        api_base="https://my-resource.openai.azure.com",
        model_prefix="azure/",
    )

    # Act
    registry.register("azure", config)
    result = registry.get("azure")

    # Assert
    assert result is config
    assert result.provider == "azure"
    assert result.api_key == "az-key-123"


def test_registry_register_overrides_existing(registry: ProviderRegistry) -> None:
    """register() with an existing name overrides the previous config."""
    # Arrange
    original = registry.get("openrouter")
    replacement = ProviderConfig(
        provider="openrouter",
        api_key="new-key",
        api_base="https://new-base.example.com",
        model_prefix="openrouter/",
    )

    # Act
    registry.register("openrouter", replacement)
    result = registry.get("openrouter")

    # Assert
    assert result is replacement
    assert result is not original
    assert result.api_key == "new-key"
    assert result.api_base == "https://new-base.example.com"


# ---------------------------------------------------------------------------
# 4.5 get() unknown provider (AC: 3)
# ---------------------------------------------------------------------------


def test_registry_get_unknown_raises_config_error(registry: ProviderRegistry) -> None:
    """get() with unknown name raises ConfigurationError with BEDDEL-CONFIG-001."""
    # Act & Assert
    with pytest.raises(ConfigurationError, match="Unknown provider") as exc_info:
        registry.get("nonexistent")

    assert exc_info.value.code == ErrorCode.CONFIG_INVALID
    assert exc_info.value.code == "BEDDEL-CONFIG-001"
    assert exc_info.value.details["provider"] == "nonexistent"


# ---------------------------------------------------------------------------
# 4.6 resolve_model() (AC: 4)
# ---------------------------------------------------------------------------


def test_resolve_model_prepends_prefix(registry: ProviderRegistry) -> None:
    """resolve_model() prepends prefix when model doesn't start with it."""
    # Act
    result = registry.resolve_model("openrouter", "anthropic/claude-3.5-sonnet")

    # Assert
    assert result == "openrouter/anthropic/claude-3.5-sonnet"


def test_resolve_model_skips_when_prefix_present(registry: ProviderRegistry) -> None:
    """resolve_model() returns model unchanged when prefix already present."""
    # Act
    result = registry.resolve_model("openrouter", "openrouter/anthropic/claude-3.5-sonnet")

    # Assert
    assert result == "openrouter/anthropic/claude-3.5-sonnet"


def test_resolve_model_no_prefix_provider(registry: ProviderRegistry) -> None:
    """resolve_model() for a provider with empty model_prefix returns model unchanged."""
    # Arrange
    registry.register("custom", ProviderConfig(provider="custom", model_prefix=""))

    # Act
    result = registry.resolve_model("custom", "gpt-4o")

    # Assert
    assert result == "gpt-4o"


# ---------------------------------------------------------------------------
# 4.7 create_adapter() (AC: 5)
# ---------------------------------------------------------------------------


def test_create_adapter_returns_litellm_adapter(registry: ProviderRegistry) -> None:
    """create_adapter() returns a LiteLLMAdapter instance."""
    # Act
    adapter = registry.create_adapter("openrouter")

    # Assert
    assert isinstance(adapter, LiteLLMAdapter)


def test_create_adapter_passes_api_key_and_api_base(registry: ProviderRegistry) -> None:
    """create_adapter() forwards api_key and api_base to the adapter."""
    # Arrange
    registry.register(
        "custom",
        ProviderConfig(
            provider="custom",
            api_key="sk-custom-key",
            api_base="https://custom.example.com/v1",
        ),
    )

    # Act
    adapter = registry.create_adapter("custom")

    # Assert
    assert adapter.api_key == "sk-custom-key"
    assert adapter.api_base == "https://custom.example.com/v1"


def test_create_adapter_passes_extra_params(registry: ProviderRegistry) -> None:
    """create_adapter() forwards extra_params to the adapter."""
    # Arrange
    registry.register(
        "custom",
        ProviderConfig(
            provider="custom",
            extra_params={"aws_region_name": "us-west-2", "custom_llm_provider": "sagemaker"},
        ),
    )

    # Act
    adapter = registry.create_adapter("custom")

    # Assert
    assert adapter.extra_params == {
        "aws_region_name": "us-west-2",
        "custom_llm_provider": "sagemaker",
    }


def test_create_adapter_no_extra_params(registry: ProviderRegistry) -> None:
    """create_adapter() for provider with no extra_params sets adapter.extra_params to None."""
    # Arrange — openrouter has no extra_params (empty dict by default)

    # Act
    adapter = registry.create_adapter("openrouter")

    # Assert
    assert adapter.extra_params is None
