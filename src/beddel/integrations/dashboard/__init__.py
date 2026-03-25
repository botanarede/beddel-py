"""Beddel Dashboard integration — execution history and monitoring API."""

from __future__ import annotations

__all__ = ["ExecutionHistoryStore"]


def __getattr__(name: str) -> object:
    """Lazy-load dashboard symbols to avoid import-time side effects.

    Follows the same pattern as the parent ``integrations/__init__.py``.
    """
    if name == "ExecutionHistoryStore":
        from beddel.integrations.dashboard.history import ExecutionHistoryStore

        return ExecutionHistoryStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
