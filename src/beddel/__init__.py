"""Beddel — Declarative YAML-based AI Workflow Engine SDK."""

from __future__ import annotations

import importlib
import warnings

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
)
from beddel.domain.strategies import (
    AgentDelegationStrategy,
    DurableExecutionStrategy,
    GoalOrientedStrategy,
)
from beddel.setup import setup as setup

__version__ = "0.1.8"

# Deprecated imports — these symbols have moved to submodules.
# The lazy import mechanism is preserved for backward compatibility but now
# emits DeprecationWarning guiding users to the correct import path.
_DEPRECATED_IMPORTS: dict[str, tuple[str, str, str]] = {
    # (module_path, attr_name, recommended_import_path)
    "BeddelSSEAdapter": (
        "beddel.integrations.sse",
        "BeddelSSEAdapter",
        "beddel.integrations",
    ),
    "CompositeMemoryProvider": (
        "beddel.adapters",
        "CompositeMemoryProvider",
        "beddel.adapters",
    ),
    "ConfigurableApprovalGate": (
        "beddel.adapters",
        "ConfigurableApprovalGate",
        "beddel.adapters",
    ),
    "DEFAULT_PII_PATTERNS": (
        "beddel.adapters.pii_tokenizer",
        "DEFAULT_PII_PATTERNS",
        "beddel.adapters",
    ),
    "InMemoryApprovalGate": (
        "beddel.adapters",
        "InMemoryApprovalGate",
        "beddel.adapters",
    ),
    "InMemoryBudgetEnforcer": (
        "beddel.adapters",
        "InMemoryBudgetEnforcer",
        "beddel.adapters",
    ),
    "InMemoryCircuitBreaker": (
        "beddel.adapters",
        "InMemoryCircuitBreaker",
        "beddel.adapters",
    ),
    "InMemoryDecisionStore": (
        "beddel.adapters",
        "InMemoryDecisionStore",
        "beddel.adapters",
    ),
    "InMemoryEventStore": (
        "beddel.adapters",
        "InMemoryEventStore",
        "beddel.adapters",
    ),
    "InMemoryMemoryProvider": (
        "beddel.adapters",
        "InMemoryMemoryProvider",
        "beddel.adapters",
    ),
    "InMemoryStateStore": (
        "beddel.adapters",
        "InMemoryStateStore",
        "beddel.adapters",
    ),
    "JSONFileStateStore": (
        "beddel.adapters",
        "JSONFileStateStore",
        "beddel.adapters",
    ),
    "LifecycleHookManager": (
        "beddel.adapters",
        "LifecycleHookManager",
        "beddel.adapters",
    ),
    "PIIMiddleware": (
        "beddel.adapters.pii_middleware",
        "PIIMiddleware",
        "beddel.adapters",
    ),
    "RegexPIITokenizer": (
        "beddel.adapters.pii_tokenizer",
        "RegexPIITokenizer",
        "beddel.adapters",
    ),
    "SQLiteEventStore": (
        "beddel.adapters",
        "SQLiteEventStore",
        "beddel.adapters",
    ),
    "StaticTierRouter": (
        "beddel.adapters",
        "StaticTierRouter",
        "beddel.adapters",
    ),
    "YAMLKnowledgeAdapter": (
        "beddel.adapters",
        "YAMLKnowledgeAdapter",
        "beddel.adapters",
    ),
    "create_beddel_handler": (
        "beddel.integrations.fastapi",
        "create_beddel_handler",
        "beddel.integrations",
    ),
    "AgentExecPrimitive": (
        "beddel.primitives.agent_exec",
        "AgentExecPrimitive",
        "beddel.primitives.agent_exec",
    ),
    "SpanT": (
        "beddel.domain.ports",
        "SpanT",
        "beddel.domain.ports",
    ),
    "StepRunner": (
        "beddel.domain.ports",
        "StepRunner",
        "beddel.domain.ports",
    ),
}


def __getattr__(name: str) -> object:
    """Lazily import deprecated symbols with a deprecation warning."""
    if name in _DEPRECATED_IMPORTS:
        module_path, attr, recommended = _DEPRECATED_IMPORTS[name]
        warnings.warn(
            f"Importing {name} from 'beddel' is deprecated. "
            f"Use 'from {recommended} import {name}' instead. "
            "This will be removed in v1.0.",
            DeprecationWarning,
            stacklevel=2,
        )
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
    "AgentError",
    "AgentResult",
    "ApprovalError",
    "ApprovalPolicy",
    "ApprovalResult",
    "ApprovalStatus",
    "BeddelError",
    "BudgetError",
    "BudgetStatus",
    "CoordinationError",
    "CoordinationResult",
    "CoordinationTask",
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
    "InterruptibleContext",
    "KitDependencyError",
    "KitManifestError",
    "KnowledgeEntry",
    "KnowledgeError",
    "KnowledgeSource",
    "MCPError",
    "MemoryEntry",
    "MemoryError",
    "NoOpTracer",
    "PIIError",
    "PIIPattern",
    "ParseError",
    "PrimitiveError",
    "ResolveError",
    "RiskLevel",
    "RiskMatrix",
    "SequentialStrategy",
    "SkillError",
    "SkillReference",
    "StateError",
    "TokenMap",
    "TracingError",
    "TriggerConfig",
    "TriggerEvent",
    "error_codes",
    "setup",
]
