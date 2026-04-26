"""Unified AG-UI endpoint — multi-workflow SSE factory.

Provides :func:`create_unified_agui_endpoint`, a factory that creates a
FastAPI :class:`~fastapi.APIRouter` routing ``POST /`` requests to the
correct workflow based on ``state.workflow_id`` or
``forwarded_props.workflow_id``.

This is the CopilotKit ``HttpAgent`` target: a single URL that
multiplexes across all loaded workflows.  When only one workflow is
loaded, it is used as the default (no ``workflow_id`` required).

The endpoint translates Beddel's internal ``BeddelEvent`` stream into
AG-UI ``BaseEvent`` instances via :class:`BeddelAGUIAdapter`, then
serializes each event as camelCase JSON (``by_alias=True``) for
AG-UI-compliant SSE delivery.

Example::

    from beddel_ag_ui.unified import create_unified_agui_endpoint

    executors = {"my-wf": (workflow, executor)}
    router = create_unified_agui_endpoint(executors)
    app.include_router(router, prefix="/ag-ui")

Requires the ``default`` extra: ``pip install beddel[default]``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import Workflow
from beddel_ag_ui.adapter import BeddelAGUIAdapter

__all__ = ["create_unified_agui_endpoint"]

logger = logging.getLogger(__name__)


#: Metadata keys excluded when extracting inputs from ``state``.
_STATE_METADATA_KEYS: frozenset[str] = frozenset(
    {"workflow_id", "workflow_name", "run_id", "inputs"}
)


async def _agui_sse_stream(
    agui_events: AsyncGenerator[Any, None],
) -> AsyncGenerator[dict[str, str], None]:
    """Wrap AG-UI BaseEvent instances as SSE-compatible dicts.

    Each event is serialized to camelCase JSON via
    ``model_dump_json(by_alias=True)`` (AG-UI convention) and yielded as
    an SSE dict with ``event`` set to the event type value and ``data``
    set to the JSON string.

    Args:
        agui_events: Async generator yielding AG-UI ``BaseEvent`` instances.

    Yields:
        Dicts with ``event`` and ``data`` keys suitable for
        ``sse-starlette``'s ``EventSourceResponse``.
    """
    async for event in agui_events:
        json_str = event.model_dump_json(by_alias=True)
        yield {"event": event.type.value, "data": json_str}


def create_unified_agui_endpoint(
    executors: dict[str, tuple[Workflow, WorkflowExecutor]],
) -> APIRouter:
    """Create a unified AG-UI router that routes by ``workflow_id``.

    Accepts a pre-built map of ``workflow_id → (workflow, executor)``
    pairs and returns an :class:`~fastapi.APIRouter` with a single
    ``POST /`` endpoint.  The endpoint parses the JSON body, resolves
    the target workflow from ``state.workflow_id`` or
    ``forwarded_props.workflow_id``, extracts inputs, and streams the
    execution result as AG-UI SSE events.

    When only one workflow is present in *executors*, it is used as the
    default — no ``workflow_id`` is required in the request body.

    Args:
        executors: Mapping of workflow IDs to ``(Workflow, WorkflowExecutor)``
            tuples.  Built by the caller (e.g. ``_build_runtime_app``)
            before mounting the router.

    Returns:
        A :class:`~fastapi.APIRouter` with a ``POST /`` endpoint that
        streams AG-UI protocol events as SSE.

    Example::

        from fastapi import FastAPI
        from beddel_ag_ui.unified import create_unified_agui_endpoint

        executors = {"demo": (workflow, executor)}
        app = FastAPI()
        router = create_unified_agui_endpoint(executors)
        app.include_router(router, prefix="/ag-ui")
    """
    router = APIRouter()

    @router.post("/", response_model=None)
    async def _handle_unified_agui(
        request: Request,
    ) -> EventSourceResponse | JSONResponse:
        """Unified AG-UI endpoint — routes by ``state.workflow_id``.

        Parses the JSON body, resolves the target workflow, extracts
        inputs, and returns an SSE stream of AG-UI events.
        """
        # ── Parse JSON body ──────────────────────────────────────────
        try:
            body: Any = await request.json()
            raw: dict[str, Any] = body if isinstance(body, dict) else {}
        except Exception:
            return JSONResponse(
                status_code=400,
                content={
                    "code": "BEDDEL-AGUI-001",
                    "message": "Invalid JSON body",
                },
            )

        # ── Resolve workflow_id ──────────────────────────────────────
        wf_id_target: str | None = None
        raw_state = raw.get("state")
        if isinstance(raw_state, dict):
            v = raw_state.get("workflow_id")
            if isinstance(v, str):
                wf_id_target = v
        if not wf_id_target:
            fwd = raw.get("forwarded_props")
            if isinstance(fwd, dict):
                v2 = fwd.get("workflow_id")
                if isinstance(v2, str):
                    wf_id_target = v2

        available = list(executors.keys())
        if not wf_id_target and len(available) == 1:
            wf_id_target = available[0]

        if not wf_id_target or wf_id_target not in executors:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "BEDDEL-AGUI-002",
                    "message": f"workflow_id not found. Available: {available}",
                },
            )

        wf_obj, executor = executors[wf_id_target]

        # ── Extract inputs ───────────────────────────────────────────
        inputs: dict[str, Any] = {}
        if isinstance(raw_state, dict):
            inputs = raw_state.get("inputs", {})
            if not inputs:
                inputs = {k: v for k, v in raw_state.items() if k not in _STATE_METADATA_KEYS}
        fwd_props = raw.get("forwarded_props")
        if isinstance(fwd_props, dict) and not inputs:
            inputs = fwd_props

        raw_thread = raw.get("thread_id")
        thread_id: str | None = raw_thread if isinstance(raw_thread, str) else None
        raw_run = raw.get("run_id")
        run_id: str | None = raw_run if isinstance(raw_run, str) else None

        # ── Execute and stream ───────────────────────────────────────
        events = executor.execute_stream(wf_obj, inputs)
        agui_events = BeddelAGUIAdapter.stream_events(
            events,
            thread_id=thread_id,
            run_id=run_id,
        )
        return EventSourceResponse(_agui_sse_stream(agui_events))

    return router
