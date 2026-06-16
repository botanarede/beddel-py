"""Agent Engine sidebar route registration.

Provides :func:`register_agent_engine_routes` which mounts three endpoints
on a FastAPI app instance:

- ``GET  /api/agent-engine/agents``   — list deployed agents via adapter
- ``POST /api/agent-engine/chat``     — stream chat via adapter (SSE)
- ``GET  /api/agent-engine/sidebar``  — serve the sidebar HTML fragment

FastAPI, Request, and SSE types are lazy-imported inside the function so
this module is importable without FastAPI on sys.path (consistent with the
rest of the serve tier).
"""

import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from .ports import IAgentRuntimeAdapter

logger = logging.getLogger(__name__)

_SIDEBAR_PATH = Path(__file__).parent / "static" / "sidebar.html"


def register_agent_engine_routes(app: Any, adapter: IAgentRuntimeAdapter) -> None:
    """Register Agent Engine sidebar API endpoints on *app*.

    Args:
        app: A FastAPI application instance (typed ``Any`` to avoid a
            hard FastAPI import at module level).
        adapter: An :class:`~.ports.IAgentRuntimeAdapter` implementation
            that supplies agent discovery and chat streaming.
    """
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse
    from sse_starlette.sse import EventSourceResponse

    @app.get("/api/agent-engine/agents")
    async def _list_agents() -> JSONResponse:
        try:
            agents = await adapter.list_agents()
            return JSONResponse(
                content=[
                    {
                        "resource_name": a.resource_name,
                        "display_name": a.display_name,
                    }
                    for a in agents
                ]
            )
        except Exception as exc:
            logger.exception("Failed to list agents")
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to list agents: {exc}"},
            )

    @app.post("/api/agent-engine/chat")
    async def _chat(request: Request) -> EventSourceResponse:
        body = await request.json()
        resource_name: str = body["resource_name"]
        message: str = body["message"]
        session_id: str | None = body.get("session_id") or None

        async def _event_generator() -> AsyncGenerator[dict[str, str], None]:
            try:
                async for chunk in adapter.chat(resource_name, message, session_id=session_id):
                    if chunk.done:
                        yield {
                            "event": "done",
                            "data": json.dumps({"session_id": chunk.session_id}),
                        }
                    else:
                        data: dict[str, str | None] = {"text": chunk.text}
                        if chunk.session_id:
                            data["session_id"] = chunk.session_id
                        yield {"event": "text_chunk", "data": json.dumps(data)}
            except Exception as exc:
                logger.exception("Error during agent chat stream")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": str(exc)}),
                }

        return EventSourceResponse(_event_generator())

    @app.get("/api/agent-engine/sidebar")
    async def _sidebar() -> HTMLResponse:
        html = _SIDEBAR_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=html)
