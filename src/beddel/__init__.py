"""Beddel — Declarative YAML-based AI Workflow Engine SDK."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from beddel.domain.errors import (
    AdapterError,
    BeddelError,
    ExecutionError,
    ParseError,
    PrimitiveError,
    ResolveError,
)
from beddel.domain.executor import SequentialStrategy
from beddel.domain.models import DefaultDependencies, InterruptibleContext
from beddel.domain.ports import (
    ExecutionDependencies,
    IExecutionStrategy,
    ILifecycleHook,
    ITracer,
    NoOpTracer,
    SpanT,
    StepRunner,
)

if TYPE_CHECKING:
    from beddel.adapters.hooks import LifecycleHookManager as LifecycleHookManager

__version__ = "0.1.0"

# Lazy imports to avoid circular dependency:
# beddel → beddel.adapters → otel_adapter → beddel.__version__
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "LifecycleHookManager": ("beddel.adapters.hooks", "LifecycleHookManager"),
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
    "BeddelError",
    "DefaultDependencies",
    "ExecutionDependencies",
    "ExecutionError",
    "IExecutionStrategy",
    "ILifecycleHook",
    "ITracer",
    "InterruptibleContext",
    "LifecycleHookManager",
    "NoOpTracer",
    "ParseError",
    "PrimitiveError",
    "ResolveError",
    "SequentialStrategy",
    "SpanT",
    "StepRunner",
]
