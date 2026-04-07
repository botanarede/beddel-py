"""Beddel — Declarative YAML-based AI Workflow Engine SDK."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from beddel import error_codes as error_codes  # re-export module
from beddel.domain.errors import (
    AdapterError,
    AgentError,
    ApprovalError,
    BeddelError,
    BudgetError,
    CoordinationError,
    DecisionError,
    DurableError,
    EventDrivenError,
    ExecutionError,
    KitDependencyError,
    KitManifestError,
    KnowledgeError,
    MCPError,
    MemoryError,
    ParseError,
    PIIError,
    PrimitiveError,
    ResolveError,
    SkillError,
    StateError,
    TracingError,
)
from beddel.domain.executor import SequentialStrategy
from beddel.domain.models import (
    AgentResult,
    ApprovalPolicy,
    ApprovalResult,
    ApprovalStatus,
    BudgetStatus,
    CoordinationResult,
    CoordinationTask,
    Decision,
    DefaultDependencies,
    Episode,
    InterruptibleContext,
    KnowledgeEntry,
    KnowledgeSource,
    MemoryEntry,
    PIIPattern,
    RiskLevel,
    RiskMatrix,
    SkillReference,
    TokenMap,
    TriggerConfig,
    TriggerEvent,
)
from beddel.domain.ports import (
    ExecutionDependencies,
    IAgentAdapter,
    IApprovalGate,
    IBudgetEnforcer,
    ICircuitBreaker,
    IContextReducer,
    ICoordinationStrategy,
    IDecisionStore,
    IEventStore,
    IExecutionStrategy,
    IHookManager,
    IKnowledgeProvider,
    ILifecycleHook,
    ILLMProvider,
    IMCPClient,
    IMemoryProvider,
    IPIITokenizer,
    IPrimitive,
    IStateStore,
    ITierRouter,
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
from beddel.setup import setup as setup

if TYPE_CHECKING:
    from beddel.adapters import CompositeMemoryProvider as CompositeMemoryProvider
    from beddel.adapters import ConfigurableApprovalGate as ConfigurableApprovalGate
    from beddel.adapters import InMemoryApprovalGate as InMemoryApprovalGate
    from beddel.adapters import InMemoryBudgetEnforcer as InMemoryBudgetEnforcer
    from beddel.adapters import InMemoryCircuitBreaker as InMemoryCircuitBreaker
    from beddel.adapters import InMemoryDecisionStore as InMemoryDecisionStore
    from beddel.adapters import InMemoryEventStore as InMemoryEventStore
    from beddel.adapters import InMemoryMemoryProvider as InMemoryMemoryProvider
    from beddel.adapters import InMemoryStateStore as InMemoryStateStore
    from beddel.adapters import JSONFileStateStore as JSONFileStateStore
    from beddel.adapters import LifecycleHookManager as LifecycleHookManager
    from beddel.adapters import SQLiteEventStore as SQLiteEventStore
    from beddel.adapters import StaticTierRouter as StaticTierRouter
    from beddel.adapters import YAMLKnowledgeAdapter as YAMLKnowledgeAdapter
    from beddel.adapters.pii_middleware import PIIMiddleware as PIIMiddleware
    from beddel.adapters.pii_tokenizer import (
        DEFAULT_PII_PATTERNS as DEFAULT_PII_PATTERNS,
    )
    from beddel.adapters.pii_tokenizer import (
        RegexPIITokenizer as RegexPIITokenizer,
    )
    from beddel.integrations.fastapi import (
        create_beddel_handler as create_beddel_handler,
    )
    from beddel.integrations.sse import BeddelSSEAdapter as BeddelSSEAdapter

__version__ = "0.1.6"

# Lazy imports to avoid circular dependency:
# beddel → beddel.adapters → otel_adapter → beddel.__version__
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BeddelSSEAdapter": ("beddel.integrations.sse", "BeddelSSEAdapter"),
    "CompositeMemoryProvider": ("beddel.adapters", "CompositeMemoryProvider"),
    "ConfigurableApprovalGate": ("beddel.adapters", "ConfigurableApprovalGate"),
    "DEFAULT_PII_PATTERNS": (
        "beddel.adapters.pii_tokenizer",
        "DEFAULT_PII_PATTERNS",
    ),
    "InMemoryApprovalGate": ("beddel.adapters", "InMemoryApprovalGate"),
    "InMemoryBudgetEnforcer": ("beddel.adapters", "InMemoryBudgetEnforcer"),
    "InMemoryCircuitBreaker": ("beddel.adapters", "InMemoryCircuitBreaker"),
    "InMemoryDecisionStore": ("beddel.adapters", "InMemoryDecisionStore"),
    "InMemoryEventStore": ("beddel.adapters", "InMemoryEventStore"),
    "InMemoryMemoryProvider": ("beddel.adapters", "InMemoryMemoryProvider"),
    "InMemoryStateStore": ("beddel.adapters", "InMemoryStateStore"),
    "JSONFileStateStore": ("beddel.adapters", "JSONFileStateStore"),
    "LifecycleHookManager": ("beddel.adapters", "LifecycleHookManager"),
    "PIIMiddleware": (
        "beddel.adapters.pii_middleware",
        "PIIMiddleware",
    ),
    "RegexPIITokenizer": (
        "beddel.adapters.pii_tokenizer",
        "RegexPIITokenizer",
    ),
    "SQLiteEventStore": ("beddel.adapters", "SQLiteEventStore"),
    "StaticTierRouter": ("beddel.adapters", "StaticTierRouter"),
    "YAMLKnowledgeAdapter": ("beddel.adapters", "YAMLKnowledgeAdapter"),
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
    "ApprovalError",
    "ApprovalPolicy",
    "ApprovalResult",
    "ApprovalStatus",
    "BeddelError",
    "BeddelSSEAdapter",
    "BudgetError",
    "BudgetStatus",
    "CompositeMemoryProvider",
    "ConfigurableApprovalGate",
    "CoordinationError",
    "CoordinationResult",
    "CoordinationTask",
    "DEFAULT_PII_PATTERNS",
    "Decision",
    "DecisionError",
    "DefaultDependencies",
    "DurableError",
    "DurableExecutionStrategy",
    "Episode",
    "EventDrivenError",
    "ExecutionDependencies",
    "ExecutionError",
    "GoalOrientedStrategy",
    "IAgentAdapter",
    "IApprovalGate",
    "IBudgetEnforcer",
    "ICircuitBreaker",
    "IContextReducer",
    "ICoordinationStrategy",
    "IDecisionStore",
    "IEventStore",
    "IExecutionStrategy",
    "IHookManager",
    "IKnowledgeProvider",
    "ILifecycleHook",
    "ILLMProvider",
    "IMCPClient",
    "IMemoryProvider",
    "IPIITokenizer",
    "IPrimitive",
    "IStateStore",
    "ITierRouter",
    "ITracer",
    "JSONFileStateStore",
    "InMemoryApprovalGate",
    "InMemoryBudgetEnforcer",
    "InMemoryCircuitBreaker",
    "InMemoryDecisionStore",
    "InMemoryEventStore",
    "InMemoryMemoryProvider",
    "InMemoryStateStore",
    "InterruptibleContext",
    "KitDependencyError",
    "KitManifestError",
    "KnowledgeEntry",
    "KnowledgeError",
    "KnowledgeSource",
    "LifecycleHookManager",
    "MCPError",
    "MemoryEntry",
    "MemoryError",
    "NoOpTracer",
    "ParseError",
    "PIIError",
    "PIIMiddleware",
    "PIIPattern",
    "PrimitiveError",
    "ResolveError",
    "RegexPIITokenizer",
    "RiskLevel",
    "RiskMatrix",
    "SequentialStrategy",
    "SkillError",
    "SkillReference",
    "SpanT",
    "SQLiteEventStore",
    "StaticTierRouter",
    "StateError",
    "StepRunner",
    "TokenMap",
    "TracingError",
    "TriggerConfig",
    "TriggerEvent",
    "YAMLKnowledgeAdapter",
    "create_beddel_handler",
    "error_codes",
    "setup",
]
