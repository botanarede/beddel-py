"""Adapters — LiteLLM, OpenTelemetry, lifecycle hooks."""

from __future__ import annotations

from beddel.adapters.litellm import LiteLLMAdapter
from beddel.adapters.provider_config import ProviderConfig, ProviderRegistry
from beddel.adapters.structured import StructuredOutputHandler

__all__ = ["LiteLLMAdapter", "ProviderConfig", "ProviderRegistry", "StructuredOutputHandler"]
