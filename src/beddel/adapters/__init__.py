"""Beddel adapters — external service integrations via ports.

Builtin adapters (no third-party deps beyond stdlib) are imported directly.
Kit-bound adapters live in their respective ``kits/`` packages and must be
imported from there (e.g. ``from beddel_provider_litellm.adapter import
LiteLLMAdapter``).
"""

from __future__ import annotations

from beddel.adapters.approval import ConfigurableApprovalGate, InMemoryApprovalGate
from beddel.adapters.budget_enforcer import InMemoryBudgetEnforcer
from beddel.adapters.circuit_breaker import InMemoryCircuitBreaker
from beddel.adapters.event_store import InMemoryEventStore, SQLiteEventStore
from beddel.adapters.hooks import LifecycleHookManager
from beddel.adapters.pii_middleware import PIIMiddleware
from beddel.adapters.pii_tokenizer import DEFAULT_PII_PATTERNS, RegexPIITokenizer
from beddel.adapters.state_store import InMemoryStateStore, JSONFileStateStore
from beddel.adapters.tier_router import StaticTierRouter

__all__ = [
    "ConfigurableApprovalGate",
    "DEFAULT_PII_PATTERNS",
    "InMemoryApprovalGate",
    "InMemoryBudgetEnforcer",
    "InMemoryCircuitBreaker",
    "InMemoryEventStore",
    "InMemoryStateStore",
    "JSONFileStateStore",
    "LifecycleHookManager",
    "PIIMiddleware",
    "RegexPIITokenizer",
    "SQLiteEventStore",
    "StaticTierRouter",
]
