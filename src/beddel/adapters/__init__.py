"""Beddel adapters — external service integrations via ports."""

from __future__ import annotations

from beddel.adapters.hooks import LifecycleHookManager
from beddel.adapters.kiro_cli import KiroCLIAgentAdapter
from beddel.adapters.litellm_adapter import LiteLLMAdapter
from beddel.adapters.otel_adapter import OpenTelemetryAdapter

__all__ = ["KiroCLIAgentAdapter", "LifecycleHookManager", "LiteLLMAdapter", "OpenTelemetryAdapter"]
