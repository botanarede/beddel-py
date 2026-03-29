"""Beddel adapters — external service integrations via ports."""

from __future__ import annotations

import contextlib

from beddel.adapters.circuit_breaker import InMemoryCircuitBreaker
from beddel.adapters.claude_adapter import ClaudeAgentAdapter
from beddel.adapters.codex_adapter import CodexAgentAdapter
from beddel.adapters.event_store import InMemoryEventStore, SQLiteEventStore
from beddel.adapters.github_auth import (
    delete_credentials,
    load_credentials,
    save_credentials,
)
from beddel.adapters.hooks import LifecycleHookManager
from beddel.adapters.kiro_cli import KiroCLIAgentAdapter
from beddel.adapters.litellm_adapter import LiteLLMAdapter
from beddel.adapters.mcp import SSEMCPClient, StdioMCPClient
from beddel.adapters.openclaw_adapter import OpenClawAgentAdapter
from beddel.adapters.otel_adapter import OpenTelemetryAdapter
from beddel.adapters.tier_router import StaticTierRouter

# Optional: langfuse is not a core dependency.
with contextlib.suppress(ImportError):
    from beddel.adapters.langfuse_tracer import LangfuseTracerAdapter as LangfuseTracerAdapter

__all__ = [
    "ClaudeAgentAdapter",
    "CodexAgentAdapter",
    "InMemoryCircuitBreaker",
    "InMemoryEventStore",
    "KiroCLIAgentAdapter",
    "LifecycleHookManager",
    "LiteLLMAdapter",
    "OpenClawAgentAdapter",
    "OpenTelemetryAdapter",
    "SSEMCPClient",
    "SQLiteEventStore",
    "StaticTierRouter",
    "StdioMCPClient",
    "delete_credentials",
    "load_credentials",
    "save_credentials",
]

# Conditionally add LangfuseTracerAdapter only when langfuse is installed.
if "LangfuseTracerAdapter" in globals():
    __all__.append("LangfuseTracerAdapter")
