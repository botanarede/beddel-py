"""Beddel Dashboard integration — execution history and monitoring API."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter

    from beddel.domain.executor import WorkflowExecutor
    from beddel.domain.models import Workflow
    from beddel.domain.ports import IAgentAdapter

__all__ = [
    "ExecutionHistoryStore",
    "create_agent_pipeline_router",
    "create_dashboard_router",
]

logger = logging.getLogger(__name__)


def create_agent_pipeline_router() -> tuple:
    """Create a FastAPI router for agent pipeline endpoints.

    Convenience re-export of
    :func:`beddel.integrations.dashboard.pipeline.create_agent_pipeline_router`.

    Returns:
        A 2-tuple of ``(APIRouter, register_adapter)`` callable.
    """
    from beddel.integrations.dashboard.pipeline import (
        create_agent_pipeline_router as _create_pipeline_router,
    )

    return _create_pipeline_router()


def create_dashboard_router(
    workflows: dict[str, Workflow],
    executor: WorkflowExecutor,
    *,
    max_history: int = 100,
    agent_adapters: dict[str, IAgentAdapter] | None = None,
) -> APIRouter:
    """Create a fully-wired Dashboard Server Protocol router.

    Wires WorkflowInspector, ExecutionHistoryStore, DashboardSSEBridge,
    and the FastAPI router into a single mountable APIRouter.

    The ``BEDDEL_MAX_HISTORY`` environment variable overrides
    ``max_history`` when set.

    Args:
        workflows: Mapping of workflow IDs to Workflow instances.
        executor: The workflow executor for running workflows.
        max_history: Maximum execution records to retain. Defaults to 100.
            Overridden by ``BEDDEL_MAX_HISTORY`` env var when set.
        agent_adapters: Optional mapping of agent IDs to
            :class:`~beddel.domain.ports.IAgentAdapter` backends.  When
            provided, a pipeline sub-router is created and each adapter
            is registered for real-time agent event translation.

    Returns:
        A FastAPI APIRouter with Dashboard Server Protocol endpoints
        mounted at ``/api``.

    Example::

        from beddel.integrations.dashboard import create_dashboard_router

        router = create_dashboard_router(workflows, executor)
        app.include_router(router)
    """
    from beddel.integrations.dashboard.bridge import DashboardSSEBridge
    from beddel.integrations.dashboard.history import ExecutionHistoryStore
    from beddel.integrations.dashboard.inspector import WorkflowInspector
    from beddel.integrations.dashboard.router import (
        create_dashboard_router as _create_router,
    )

    env_max = os.environ.get("BEDDEL_MAX_HISTORY")
    effective_max = max_history
    if env_max is not None:
        try:
            parsed = int(env_max)
            effective_max = max(1, parsed)
        except ValueError:
            logger.warning(
                "Invalid BEDDEL_MAX_HISTORY=%r, using default %d",
                env_max,
                max_history,
            )

    inspector = WorkflowInspector(workflows)
    history = ExecutionHistoryStore(max_entries=effective_max)
    bridge = DashboardSSEBridge(executor=executor, history=history)

    router = _create_router(
        inspector=inspector,
        bridge=bridge,
        history=history,
        workflows=workflows,
    )

    if agent_adapters is not None:
        from beddel.integrations.dashboard.pipeline import (
            create_agent_pipeline_router as _create_pipeline_router,
        )
        from beddel.integrations.dashboard.pipeline.agent_adapter import (
            AgentPipelineAdapter,
        )

        agent_router, register_adapter = _create_pipeline_router()
        for agent_id, backend in agent_adapters.items():
            pipeline_adapter = AgentPipelineAdapter(
                agent_id=agent_id,
                backend=type(backend).__name__,
            )
            register_adapter(agent_id, pipeline_adapter, backend)
        router.include_router(agent_router)

    return router


def __getattr__(name: str) -> object:
    """Lazy-load dashboard symbols to avoid import-time side effects."""
    if name == "ExecutionHistoryStore":
        from beddel.integrations.dashboard.history import ExecutionHistoryStore

        return ExecutionHistoryStore
    if name == "create_agent_pipeline_router":
        from beddel.integrations.dashboard.pipeline import (
            create_agent_pipeline_router,
        )

        return create_agent_pipeline_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
