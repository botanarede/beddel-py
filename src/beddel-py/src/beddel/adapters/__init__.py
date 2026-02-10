"""Adapters — LiteLLM, OpenTelemetry, lifecycle hooks."""

from __future__ import annotations

from beddel.adapters.hooks import LifecycleHooksAdapter
from beddel.adapters.litellm import LiteLLMAdapter
from beddel.adapters.provider_config import ProviderConfig, ProviderRegistry
from beddel.adapters.structured import StructuredOutputHandler

__all__ = [
    "LifecycleHooksAdapter",
    "LiteLLMAdapter",
    "ProviderConfig",
    "ProviderRegistry",
    "StructuredOutputHandler",
]
