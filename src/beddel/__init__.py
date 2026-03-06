"""Beddel — Declarative YAML-based AI Workflow Engine SDK."""

from __future__ import annotations

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
    ITracer,
    NoOpTracer,
    SpanT,
    StepRunner,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AdapterError",
    "BeddelError",
    "DefaultDependencies",
    "ExecutionDependencies",
    "ExecutionError",
    "IExecutionStrategy",
    "ITracer",
    "InterruptibleContext",
    "NoOpTracer",
    "ParseError",
    "PrimitiveError",
    "ResolveError",
    "SequentialStrategy",
    "SpanT",
    "StepRunner",
]
