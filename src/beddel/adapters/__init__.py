"""Beddel adapters — external service integrations via ports.

Builtin adapters (no third-party deps beyond stdlib) are imported directly.
Kit-bound adapters that were moved to ``kits/`` are available via lazy
``__getattr__`` with a :class:`DeprecationWarning` guiding callers to the
new kit import path.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from pathlib import Path
from typing import Any

from beddel.adapters.approval import ConfigurableApprovalGate, InMemoryApprovalGate
from beddel.adapters.budget_enforcer import InMemoryBudgetEnforcer
from beddel.adapters.circuit_breaker import InMemoryCircuitBreaker
from beddel.adapters.event_store import InMemoryEventStore, SQLiteEventStore
from beddel.adapters.hooks import LifecycleHookManager
from beddel.adapters.tier_router import StaticTierRouter

__all__ = [
    "ConfigurableApprovalGate",
    "InMemoryApprovalGate",
    "InMemoryBudgetEnforcer",
    "InMemoryCircuitBreaker",
    "InMemoryEventStore",
    "LifecycleHookManager",
    "SQLiteEventStore",
    "StaticTierRouter",
]

# ---------------------------------------------------------------------------
# Project root — used to locate kit ``src/`` directories for sys.path
# ---------------------------------------------------------------------------
# __file__ = .../beddel/src/beddel-py/src/beddel/adapters/__init__.py
#   parents[0] = adapters/
#   parents[1] = beddel/
#   parents[2] = src/          (beddel-py/src)
#   parents[3] = beddel-py/
#   parents[4] = src/          (top-level src/)
#   parents[5] = beddel/       (project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[5]

# ---------------------------------------------------------------------------
# Deprecated kit-bound adapter mapping
# ---------------------------------------------------------------------------
# Each entry: name -> (kit_dir_name, kit_module, attr_name, suggested_import)
_DEPRECATED_IMPORTS: dict[str, tuple[str, str, str, str]] = {
    "LiteLLMAdapter": (
        "provider-litellm-kit",
        "beddel_provider_litellm.adapter",
        "LiteLLMAdapter",
        "from beddel_provider_litellm.adapter import LiteLLMAdapter",
    ),
    "OpenTelemetryAdapter": (
        "observability-otel-kit",
        "beddel_observability_otel.adapter",
        "OpenTelemetryAdapter",
        "from beddel_observability_otel.adapter import OpenTelemetryAdapter",
    ),
    "LangfuseTracerAdapter": (
        "observability-langfuse-kit",
        "beddel_observability_langfuse.adapter",
        "LangfuseTracerAdapter",
        "from beddel_observability_langfuse.adapter import LangfuseTracerAdapter",
    ),
    "OpenClawAgentAdapter": (
        "agent-openclaw-kit",
        "beddel_agent_openclaw.adapter",
        "OpenClawAgentAdapter",
        "from beddel_agent_openclaw.adapter import OpenClawAgentAdapter",
    ),
    "ClaudeAgentAdapter": (
        "agent-claude-kit",
        "beddel_agent_claude.adapter",
        "ClaudeAgentAdapter",
        "from beddel_agent_claude.adapter import ClaudeAgentAdapter",
    ),
    "CodexAgentAdapter": (
        "agent-codex-kit",
        "beddel_agent_codex.adapter",
        "CodexAgentAdapter",
        "from beddel_agent_codex.adapter import CodexAgentAdapter",
    ),
    "KiroCLIAgentAdapter": (
        "agent-kiro-kit",
        "beddel_agent_kiro.adapter",
        "KiroCLIAgentAdapter",
        "from beddel_agent_kiro.adapter import KiroCLIAgentAdapter",
    ),
    "StdioMCPClient": (
        "protocol-mcp-kit",
        "beddel_protocol_mcp.stdio_client",
        "StdioMCPClient",
        "from beddel_protocol_mcp.stdio_client import StdioMCPClient",
    ),
    "SSEMCPClient": (
        "protocol-mcp-kit",
        "beddel_protocol_mcp.sse_client",
        "SSEMCPClient",
        "from beddel_protocol_mcp.sse_client import SSEMCPClient",
    ),
    "delete_credentials": (
        "auth-github-kit",
        "beddel_auth_github.provider",
        "delete_credentials",
        "from beddel_auth_github.provider import delete_credentials",
    ),
    "load_credentials": (
        "auth-github-kit",
        "beddel_auth_github.provider",
        "load_credentials",
        "from beddel_auth_github.provider import load_credentials",
    ),
    "save_credentials": (
        "auth-github-kit",
        "beddel_auth_github.provider",
        "save_credentials",
        "from beddel_auth_github.provider import save_credentials",
    ),
}


def _ensure_kit_on_path(kit_dir_name: str) -> None:
    """Add a kit's ``src/`` directory to ``sys.path`` if not already present."""
    kit_src = str(_PROJECT_ROOT / "kits" / kit_dir_name / "src")
    if kit_src not in sys.path:
        sys.path.insert(0, kit_src)


def __getattr__(name: str) -> Any:
    """Lazy import of kit-bound adapters with deprecation warning."""
    if name in _DEPRECATED_IMPORTS:
        kit_dir, kit_module, attr_name, suggested = _DEPRECATED_IMPORTS[name]
        warnings.warn(
            f"Importing {name!r} from 'beddel.adapters' is deprecated. Use: {suggested}",
            DeprecationWarning,
            stacklevel=2,
        )
        _ensure_kit_on_path(kit_dir)
        mod = importlib.import_module(kit_module)
        value = getattr(mod, attr_name)
        globals()[name] = value  # cache for subsequent access
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
