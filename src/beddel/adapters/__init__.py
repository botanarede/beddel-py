"""Beddel adapters — external service integrations via ports."""

from __future__ import annotations

from beddel.adapters.circuit_breaker import InMemoryCircuitBreaker
from beddel.adapters.event_store import InMemoryEventStore, SQLiteEventStore
from beddel.adapters.hooks import LifecycleHookManager
from beddel.adapters.kiro_cli import KiroCLIAgentAdapter
from beddel.adapters.litellm_adapter import LiteLLMAdapter
from beddel.adapters.otel_adapter import OpenTelemetryAdapter

__all__ = [
    "InMemoryCircuitBreaker",
    "InMemoryEventStore",
    "KiroCLIAgentAdapter",
    "LifecycleHookManager",
    "LiteLLMAdapter",
    "OpenTelemetryAdapter",
    "SQLiteEventStore",
]
