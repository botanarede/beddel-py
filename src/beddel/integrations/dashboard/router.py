"""Dashboard Server Protocol router — 6 REST + SSE endpoints.

Provides :func:`create_dashboard_router`, a factory that returns a FastAPI
:class:`~fastapi.APIRouter` implementing the Dashboard Server Protocol.
The router is mountable on any existing FastAPI app via
``app.include_router(dashboard_router)``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from beddel.domain.models import Workflow
from beddel.integrations.dashboard.bridge import DashboardSSEBridge
from beddel.integrations.dashboard.history import ExecutionHistoryStore
from beddel.integrations.dashboard.inspector import WorkflowInspector

__all__ = ["create_dashboard_router"]

logger = logging.getLogger(__name__)


def create_dashboard_router(
    *,
    inspector: WorkflowInspector,
    bridge: DashboardSSEBridge,
    history: ExecutionHistoryStore,
    workflows: dict[str, Workflow],
) -> APIRouter:
    """Create a FastAPI router with Dashboard Server Protocol endpoints.

    Args:
        inspector: Workflow metadata inspector.
        bridge: SSE bridge for executing and streaming workflows.
        history: Execution history store.
        workflows: Mapping of workflow IDs to Workflow objects.

    Returns:
        An APIRouter with 6 endpoints mounted at ``/api`` prefix.
    """
    router = APIRouter(prefix="/api")
    active_streams: dict[str, AsyncGenerator[dict[str, str], None]] = {}

    @router.get("/workflows")
    async def list_workflows() -> list[dict[str, Any]]:
        """Return lightweight summaries of all registered workflows."""
        return inspector.list_workflows()

    @router.get("/workflows/{workflow_id}", response_model=None)
    async def get_workflow(workflow_id: str) -> JSONResponse:
        """Return full detail for a single workflow, or 404."""
        detail = inspector.get_workflow_detail(workflow_id)
        if detail is None:
            return JSONResponse(status_code=404, content={"detail": "Workflow not found"})
        return JSONResponse(content=detail)

    @router.post("/workflows/{workflow_id}/run", response_model=None)
    async def run_workflow(workflow_id: str, request: Request) -> JSONResponse:
        """Trigger workflow execution and return run_id + stream URL."""
        workflow = workflows.get(workflow_id)
        if workflow is None:
            return JSONResponse(status_code=404, content={"detail": "Workflow not found"})
        try:
            body = await request.json()
            inputs: dict[str, Any] = body if isinstance(body, dict) else {}
        except Exception:
            inputs = {}
        run_id, stream = await bridge.execute_and_stream(workflow, inputs)
        active_streams[run_id] = stream
        return JSONResponse(
            content={
                "run_id": run_id,
                "stream_url": f"/api/workflows/{workflow_id}/events/{run_id}",
            },
        )

    @router.get("/workflows/{workflow_id}/events/{exec_id}", response_model=None)
    async def stream_events(workflow_id: str, exec_id: str) -> EventSourceResponse | JSONResponse:
        """Stream SSE events for a running execution, or 404."""
        stream = active_streams.pop(exec_id, None)
        if stream is None:
            return JSONResponse(status_code=404, content={"detail": "Stream not found"})
        return EventSourceResponse(stream)

    @router.get("/executions")
    async def list_executions() -> list[dict[str, Any]]:
        """Return summaries of all execution records."""
        records = history.list_all()
        return [
            {
                "id": r.run_id,
                "workflow_id": r.workflow_id,
                "status": r.status,
                "started_at": r.started_at.isoformat(),
                "total_duration": r.total_duration,
            }
            for r in records
        ]

    @router.get("/executions/{exec_id}", response_model=None)
    async def get_execution(exec_id: str) -> JSONResponse:
        """Return full detail for a single execution, or 404."""
        record = history.get(exec_id)
        if record is None:
            return JSONResponse(status_code=404, content={"detail": "Execution not found"})
        return JSONResponse(content=record.model_dump(mode="json"))

    return router
