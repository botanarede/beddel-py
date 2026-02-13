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
from beddel.domain.models import InterruptibleContext
from beddel.domain.ports import IExecutionStrategy

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "BeddelError",
    "ParseError",
    "ResolveError",
    "ExecutionError",
    "PrimitiveError",
    "AdapterError",
    "IExecutionStrategy",
    "InterruptibleContext",
    "SequentialStrategy",
]
