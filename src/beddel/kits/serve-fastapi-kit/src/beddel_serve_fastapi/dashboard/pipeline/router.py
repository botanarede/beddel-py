"""Agent pipeline router — health check, SSE stream, and execute endpoints.

Provides :func:`create_agent_pipeline_router`, a factory that returns a
FastAPI :class:`~fastapi.APIRouter` and a ``register_adapter`` closure for
wiring agent backends at startup.

Endpoints:

- ``GET /api/pipeline/agents/status`` — health check for all registered adapters
- ``GET /api/pipeline/agents/events`` — SSE stream of pipeline events
- ``POST /api/pipeline/agents/{agent_id}/execute`` — execute a prompt via adapter
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncGenerator, Callable
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from beddel.domain.errors import AgentError
from beddel.integrations.dashboard.pipeline.agent_adapter import (
    AgentPipelineAdapter,
)
from beddel.integrations.dashboard.pipeline.models import AgentPipelineEvent

if TYPE_CHECKING:
    from beddel.domain.ports import IAgentAdapter

__all__ = ["create_agent_pipeline_router"]

logger = logging.getLogger(__name__)

RegisterAdapterFn = Callable[[str, AgentPipelineAdapter, "IAgentAdapter"], None]


def create_agent_pipeline_router() -> tuple[APIRouter, RegisterAdapterFn]:
    """Create a FastAPI router for agent pipeline endpoints.

    Returns a ``(router, register_adapter)`` tuple.  The ``register_adapter``
    closure stores adapters in internal dicts used by the endpoints.

    Returns:
        A 2-tuple of:
        - ``APIRouter`` with prefix ``/api/pipeline/agents``
        - ``register_adapter(agent_id, adapter, agent_backend)`` callable
    """
    router = APIRouter(prefix="/api/pipeline/agents")

    pipeline_adapters: dict[str, AgentPipelineAdapter] = {}
    agent_backends: dict[str, IAgentAdapter] = {}
    event_queue: asyncio.Queue[AgentPipelineEvent] = asyncio.Queue()

    def register_adapter(
        agent_id: str,
        adapter: AgentPipelineAdapter,
        agent_backend: IAgentAdapter,
    ) -> None:
        """Register a pipeline adapter and its backing agent adapter."""
        pipeline_adapters[agent_id] = adapter
        agent_backends[agent_id] = agent_backend
        logger.info("Registered pipeline adapter: %s", agent_id)

    # ------------------------------------------------------------------
    # GET /status — health check for all registered adapters
    # ------------------------------------------------------------------
    @router.get("/status")
    async def agent_status() -> dict[str, Any]:
        """Return health status for all registered agent adapters."""
        agents = [dataclasses.asdict(adapter.health()) for adapter in pipeline_adapters.values()]
        active = sum(1 for a in agents if a["status"] == "connected")
        return {
            "agents": agents,
            "active_count": active,
            "total_count": len(agents),
        }

    # ------------------------------------------------------------------
    # GET /events — SSE stream of pipeline events
    # ------------------------------------------------------------------
    @router.get("/events")
    async def agent_events() -> EventSourceResponse:
        """Stream agent pipeline events via SSE."""

        async def _generate() -> AsyncGenerator[dict[str, str], None]:
            while True:
                event = await event_queue.get()
                payload = dataclasses.asdict(event)
                yield {
                    "event": event.event_type,
                    "data": _json_dumps(payload),
                }

        return EventSourceResponse(_generate())

    # ------------------------------------------------------------------
    # POST /{agent_id}/execute — delegate to agent backend
    # ------------------------------------------------------------------
    @router.post("/{agent_id}/execute", response_model=None)
    async def execute_agent(agent_id: str, request: Request) -> JSONResponse:
        """Execute a prompt via the named agent adapter."""
        adapter = pipeline_adapters.get(agent_id)
        backend = agent_backends.get(agent_id)
        if adapter is None or backend is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"Agent '{agent_id}' not found"},
            )

        body: dict[str, Any] = await request.json()
        prompt: str = body.get("prompt", "")
        sandbox: str = body.get("sandbox", "read-only")

        adapter.mark_active()
        try:
            result = await backend.execute(prompt, sandbox=sandbox)
            events = adapter.translate_result(result)
            # Langfuse trace link enrichment (AC 6)
            _enrich_langfuse_trace(events, result.usage)
            for ev in events:
                await event_queue.put(ev)
            adapter.mark_inactive()
            return JSONResponse(
                content={
                    "agent_id": agent_id,
                    "status": "completed",
                    "events_count": len(events),
                },
            )
        except AgentError as exc:
            error_event = adapter.translate_error(exc)
            await event_queue.put(error_event)
            adapter.mark_inactive()
            return JSONResponse(
                content={
                    "agent_id": agent_id,
                    "status": "failed",
                    "events_count": 1,
                },
            )

    return router, register_adapter


def _enrich_langfuse_trace(
    events: list[AgentPipelineEvent],
    usage: dict[str, Any],
) -> None:
    """Add ``langfuse_trace_url`` to ``step_end`` events when trace_id present."""
    trace_id = usage.get("trace_id")
    if trace_id is None:
        return
    for event in events:
        if event.event_type == "step_end":
            event.payload["langfuse_trace_url"] = f"/traces/{trace_id}"


def _json_dumps(obj: Any) -> str:
    """Serialize *obj* to a compact JSON string."""
    import json

    return json.dumps(obj, separators=(",", ":"))
