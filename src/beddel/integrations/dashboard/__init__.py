"""Beddel Dashboard integration — execution history and monitoring API."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import Workflow
from beddel.integrations.dashboard.bridge import DashboardSSEBridge
from beddel.integrations.dashboard.history import ExecutionHistoryStore
from beddel.integrations.dashboard.inspector import WorkflowInspector

if TYPE_CHECKING:
    from fastapi import APIRouter

__all__ = ["ExecutionHistoryStore", "create_dashboard_router"]


def create_dashboard_router(
    workflows: dict[str, Workflow],
    executor: WorkflowExecutor,
    *,
    max_history: int = 100,
) -> APIRouter:
    """Create a fully-wired Dashboard Server Protocol router.

    Wires :class:`WorkflowInspector`, :class:`ExecutionHistoryStore`,
    :class:`DashboardSSEBridge`, and the FastAPI router into a single
    mountable :class:`~fastapi.APIRouter`.

    The ``BEDDEL_MAX_HISTORY`` environment variable overrides
    ``max_history`` when set.

    Args:
        workflows: Mapping of workflow IDs to :class:`Workflow` instances.
        executor: The workflow executor for running workflows.
        max_history: Maximum execution records to retain. Defaults to 100.
            Overridden by ``BEDDEL_MAX_HISTORY`` env var when set.

    Returns:
        A FastAPI :class:`~fastapi.APIRouter` with 6 Dashboard Server
        Protocol endpoints mounted at ``/api``.

    Example::

        from beddel.integrations.dashboard import create_dashboard_router

        router = create_dashboard_router(workflows, executor)
        app.include_router(router)
    """
    from beddel.integrations.dashboard.router import (
        create_dashboard_router as _create_router,
    )

    env_max = os.environ.get("BEDDEL_MAX_HISTORY")
    effective_max = int(env_max) if env_max is not None else max_history

    inspector = WorkflowInspector(workflows)
    history = ExecutionHistoryStore(max_entries=effective_max)
    bridge = DashboardSSEBridge(executor=executor, history=history)

    return _create_router(
        inspector=inspector,
        bridge=bridge,
        history=history,
        workflows=workflows,
    )


def __getattr__(name: str) -> object:
    """Lazy-load dashboard symbols to avoid import-time side effects.

    Follows the same pattern as the parent ``integrations/__init__.py``.
    """
    if name == "ExecutionHistoryStore":
        from beddel.integrations.dashboard.history import ExecutionHistoryStore

        return ExecutionHistoryStore
    if name == "create_dashboard_router":
        return create_dashboard_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
