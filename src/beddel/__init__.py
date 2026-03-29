"""Beddel — Declarative YAML-based AI Workflow Engine SDK."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from beddel import error_codes as error_codes  # re-export module
from beddel.domain.errors import (
    AdapterError,
    AgentError,
    BeddelError,
    DurableError,
    ExecutionError,
    MCPError,
    ParseError,
    PrimitiveError,
    ResolveError,
    TracingError,
)
from beddel.domain.executor import SequentialStrategy
from beddel.domain.models import AgentResult, DefaultDependencies, InterruptibleContext
from beddel.domain.ports import (
    ExecutionDependencies,
    IAgentAdapter,
    ICircuitBreaker,
    IEventStore,
    IExecutionStrategy,
    ILifecycleHook,
    IMCPClient,
    ITracer,
    NoOpTracer,
    SpanT,
    StepRunner,
)
from beddel.domain.strategies import (
    AgentDelegationStrategy,
    DurableExecutionStrategy,
    GoalOrientedStrategy,
)
from beddel.primitives.agent_exec import AgentExecPrimitive

if TYPE_CHECKING:
    from beddel.adapters.claude_adapter import ClaudeAgentAdapter as ClaudeAgentAdapter
    from beddel.adapters.event_store import SQLiteEventStore as SQLiteEventStore
    from beddel.adapters.hooks import LifecycleHookManager as LifecycleHookManager
    from beddel.adapters.kiro_cli import KiroCLIAgentAdapter as KiroCLIAgentAdapter
    from beddel.adapters.mcp import SSEMCPClient as SSEMCPClient
    from beddel.adapters.mcp import StdioMCPClient as StdioMCPClient
    from beddel.adapters.openclaw_adapter import OpenClawAgentAdapter as OpenClawAgentAdapter
    from beddel.integrations.fastapi import (
        create_beddel_handler as create_beddel_handler,
    )
    from beddel.integrations.sse import BeddelSSEAdapter as BeddelSSEAdapter

__version__ = "0.1.3"

# Lazy imports to avoid circular dependency:
# beddel → beddel.adapters → otel_adapter → beddel.__version__
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BeddelSSEAdapter": ("beddel.integrations.sse", "BeddelSSEAdapter"),
    "ClaudeAgentAdapter": ("beddel.adapters.claude_adapter", "ClaudeAgentAdapter"),
    "KiroCLIAgentAdapter": ("beddel.adapters.kiro_cli", "KiroCLIAgentAdapter"),
    "LifecycleHookManager": ("beddel.adapters.hooks", "LifecycleHookManager"),
    "OpenClawAgentAdapter": ("beddel.adapters.openclaw_adapter", "OpenClawAgentAdapter"),
    "SQLiteEventStore": ("beddel.adapters.event_store", "SQLiteEventStore"),
    "SSEMCPClient": ("beddel.adapters.mcp", "SSEMCPClient"),
    "StdioMCPClient": ("beddel.adapters.mcp", "StdioMCPClient"),
    "create_beddel_handler": (
        "beddel.integrations.fastapi",
        "create_beddel_handler",
    ),
}


def __getattr__(name: str) -> object:
    """Lazily import adapter symbols to break circular imports."""
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        mod = importlib.import_module(module_path)
        value = getattr(mod, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "__version__",
    "AdapterError",
    "AgentDelegationStrategy",
    "AgentExecPrimitive",
    "AgentError",
    "AgentResult",
    "BeddelError",
    "BeddelSSEAdapter",
    "ClaudeAgentAdapter",
    "DefaultDependencies",
    "DurableError",
    "DurableExecutionStrategy",
    "ExecutionDependencies",
    "ExecutionError",
    "GoalOrientedStrategy",
    "IAgentAdapter",
    "ICircuitBreaker",
    "IEventStore",
    "IExecutionStrategy",
    "ILifecycleHook",
    "IMCPClient",
    "ITracer",
    "InterruptibleContext",
    "KiroCLIAgentAdapter",
    "LifecycleHookManager",
    "MCPError",
    "NoOpTracer",
    "OpenClawAgentAdapter",
    "ParseError",
    "PrimitiveError",
    "ResolveError",
    "SequentialStrategy",
    "SpanT",
    "SSEMCPClient",
    "SQLiteEventStore",
    "StdioMCPClient",
    "StepRunner",
    "TracingError",
    "create_beddel_handler",
    "error_codes",
]
