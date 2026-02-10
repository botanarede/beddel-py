"""Adapters — LiteLLM, OpenTelemetry, lifecycle hooks."""

from __future__ import annotations

from beddel.adapters.litellm import LiteLLMAdapter
from beddel.adapters.structured import StructuredOutputHandler

__all__ = ["LiteLLMAdapter", "StructuredOutputHandler"]
