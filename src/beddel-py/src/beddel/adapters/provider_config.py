"""Provider configuration — registry of LLM provider settings."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from beddel.adapters.litellm import LiteLLMAdapter
from beddel.domain.models import ConfigurationError, ErrorCode

logger = logging.getLogger("beddel.adapters.provider_config")


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider.

    Attributes:
        provider: Provider identifier (e.g. ``"openrouter"``, ``"gemini"``).
        api_key: Optional API key — should come from env vars, never hardcoded.
        api_base: Optional base URL override for the provider endpoint.
        model_prefix: Prefix prepended to model names when routing via LiteLLM
            (e.g. ``"openrouter/"``).  Empty string means no prefix.
        extra_params: Arbitrary provider-specific parameters forwarded to the
            adapter in a future release.
    """

    provider: str
    api_key: str | None = None
    api_base: str | None = None
    model_prefix: str = ""
    extra_params: dict[str, Any] = Field(default_factory=dict)


class ProviderRegistry:
    """Registry mapping provider names to their :class:`ProviderConfig`.

    On construction the registry is pre-populated with sensible defaults for
    ``openrouter``, ``gemini``, and ``bedrock``.  Callers can override any
    built-in entry via :meth:`register`.
    """

    def __init__(self) -> None:
        self._providers: dict[str, ProviderConfig] = {}
        self._register_defaults()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, name: str, config: ProviderConfig) -> None:
        """Add or override a provider configuration.

        Args:
            name: Canonical provider name (lower-case by convention).
            config: The :class:`ProviderConfig` to associate with *name*.
        """
        logger.debug("register provider: name=%s prefix=%s", name, config.model_prefix)
        self._providers[name] = config

    def get(self, name: str) -> ProviderConfig:
        """Retrieve a provider configuration by name.

        Args:
            name: The provider name previously registered.

        Returns:
            The matching :class:`ProviderConfig`.

        Raises:
            ConfigurationError: If *name* is not registered
                (code ``BEDDEL-CONFIG-001``).
        """
        try:
            return self._providers[name]
        except KeyError:
            raise ConfigurationError(
                f"Unknown provider: {name!r}",
                code=ErrorCode.CONFIG_INVALID,
                details={"provider": name},
            ) from None

    def resolve_model(self, provider_name: str, model_name: str) -> str:
        """Return the fully-qualified model string for LiteLLM.

        If *model_name* already starts with the provider's ``model_prefix``
        the name is returned unchanged; otherwise the prefix is prepended.

        Args:
            provider_name: Registered provider name.
            model_name: Raw model identifier (e.g. ``"gpt-4o"``).

        Returns:
            Model string suitable for ``litellm.acompletion(model=...)``.
        """
        config = self.get(provider_name)
        prefix = config.model_prefix

        if not prefix or model_name.startswith(prefix):
            logger.debug(
                "resolve_model: provider=%s model=%s (no prefix needed)",
                provider_name,
                model_name,
            )
            return model_name

        resolved = f"{prefix}{model_name}"
        logger.debug(
            "resolve_model: provider=%s model=%s -> %s",
            provider_name,
            model_name,
            resolved,
        )
        return resolved

    def create_adapter(self, provider_name: str) -> LiteLLMAdapter:
        """Create a :class:`LiteLLMAdapter` configured for *provider_name*.

        Forwards ``api_key``, ``api_base``, and any ``extra_params`` defined
        in the provider configuration to the adapter constructor.

        Args:
            provider_name: Registered provider name.

        Returns:
            A ready-to-use :class:`LiteLLMAdapter` instance.
        """
        config = self.get(provider_name)
        logger.debug(
            "create_adapter: provider=%s api_base=%s extra_params=%s",
            provider_name,
            config.api_base,
            list(config.extra_params.keys()) if config.extra_params else None,
        )
        return LiteLLMAdapter(
            api_key=config.api_key,
            api_base=config.api_base,
            extra_params=config.extra_params or None,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        """Populate the registry with built-in provider defaults."""
        defaults: list[ProviderConfig] = [
            ProviderConfig(
                provider="openrouter",
                model_prefix="openrouter/",
                api_base="https://openrouter.ai/api/v1",
            ),
            ProviderConfig(
                provider="gemini",
                model_prefix="gemini/",
            ),
            ProviderConfig(
                provider="bedrock",
                model_prefix="bedrock/",
            ),
        ]
        for cfg in defaults:
            self._providers[cfg.provider] = cfg

        logger.debug(
            "registered %d built-in providers: %s",
            len(defaults),
            ", ".join(cfg.provider for cfg in defaults),
        )
