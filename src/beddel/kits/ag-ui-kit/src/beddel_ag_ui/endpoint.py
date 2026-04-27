"""FastAPI AG-UI endpoint — workflow-to-AG-UI SSE factory.

Provides :func:`create_agui_endpoint`, a factory that wires a
:class:`~beddel.domain.models.Workflow` into a FastAPI
:class:`~fastapi.APIRouter` with AG-UI protocol SSE streaming and
structured error responses.

The endpoint translates Beddel's internal ``BeddelEvent`` stream into
AG-UI ``BaseEvent`` instances via :class:`BeddelAGUIAdapter`, then
serializes each event as camelCase JSON (``by_alias=True``) for
AG-UI-compliant SSE delivery.

Example::

    from beddel.domain.models import Workflow
    from beddel_ag_ui.endpoint import create_agui_endpoint

    workflow = Workflow(...)
    router = create_agui_endpoint(workflow)
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

from beddel.domain.errors import BeddelError, ParseError, ResolveError
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import DefaultDependencies, Workflow
from beddel.domain.ports import IHookManager, ILLMProvider, ITracer
from beddel.domain.registry import PrimitiveRegistry
from beddel.error_codes import INTERNAL_SERVER_ERROR
from beddel.primitives import register_builtins
from beddel_ag_ui.adapter import BeddelAGUIAdapter

__all__ = ["create_agui_endpoint"]

logger = logging.getLogger(__name__)

# Client-error subclasses → HTTP 422
_CLIENT_ERRORS: tuple[type[BeddelError], ...] = (ParseError, ResolveError)


def _extract_inputs(body: dict[str, Any]) -> dict[str, Any]:
    """Extract workflow inputs from the POST body.

    The body can be either:

    - A ``RunAgentInput``-like dict with ``state``, ``forwarded_props``,
      etc.  In this case, ``state`` or ``forwarded_props`` are used as
      workflow inputs.
    - A raw dict with workflow inputs directly.

    A2UI actions (BC9.5): When the dashboard forwards an A2UI action,
    the ``state`` dict contains an ``a2ui_action`` key with the action
    data (name, surfaceId, context). This is passed through as a normal
    workflow input, accessible via ``$input.a2ui_action`` in workflow steps.

    Args:
        body: Parsed JSON body from the POST request.

    Returns:
        A dict of workflow inputs.
    """
    # RunAgentInput format: prefer state, then forwarded_props
    if "state" in body and isinstance(body["state"], dict):
        return body["state"]
    if "forwarded_props" in body and isinstance(body["forwarded_props"], dict):
        return body["forwarded_props"]
    # Fall back to the raw body as inputs
    return body


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


def create_agui_endpoint(
    workflow: Workflow,
    *,
    provider: ILLMProvider | None = None,
    registry: PrimitiveRegistry | None = None,
    hooks: IHookManager | None = None,
    tracer: ITracer | None = None,
    deps: DefaultDependencies | None = None,
) -> APIRouter:
    """Create a FastAPI router that exposes a workflow as an AG-UI SSE endpoint.

    Wires all dependencies (provider, registry, executor) and returns an
    :class:`~fastapi.APIRouter` with a single ``POST /`` endpoint.  The
    endpoint accepts a JSON body (optionally in ``RunAgentInput`` format),
    executes the workflow via streaming, translates events to the AG-UI
    protocol, and returns an SSE response.

    When ``deps`` is provided, the executor is constructed directly with
    the pre-built dependency container, bypassing individual ``provider``,
    ``hooks``, and ``tracer`` wiring.  This is the preferred approach for
    callers that already have a :class:`DefaultDependencies` instance.

    When ``deps`` is ``None`` (the default), individual parameters are
    used to construct the executor (backward-compatible behaviour):

    - When ``provider`` is ``None``, a
      :class:`~beddel.adapters.litellm_adapter.LiteLLMAdapter` is created
      as the default LLM provider.
    - When ``registry`` is ``None``, a fresh
      :class:`~beddel.domain.registry.PrimitiveRegistry` is created and
      populated with all built-in primitives via
      :func:`~beddel.primitives.register_builtins`.

    Args:
        workflow: The workflow definition to expose as an AG-UI endpoint.
        provider: Optional LLM provider.  Defaults to
            :class:`~beddel.adapters.litellm_adapter.LiteLLMAdapter`.
            Ignored when ``deps`` is provided.
        registry: Optional primitive registry.  Defaults to a new registry
            with all built-in primitives registered.
        hooks: Optional :class:`IHookManager` instance forwarded to the
            executor.  Ignored when ``deps`` is provided.
        tracer: Optional :class:`ITracer` instance for distributed tracing.
            Forwarded to the executor.  Defaults to ``None`` (no tracing).
            Ignored when ``deps`` is provided.
        deps: Optional pre-built :class:`DefaultDependencies` container.
            When provided, takes precedence over ``provider``, ``hooks``,
            and ``tracer`` — the executor is constructed with ``deps``
            directly.

    Returns:
        A :class:`~fastapi.APIRouter` with a ``POST /`` endpoint that
        streams AG-UI protocol events as SSE.

    Example::

        from fastapi import FastAPI
        from beddel.domain.models import Workflow
        from beddel_ag_ui.endpoint import create_agui_endpoint

        app = FastAPI()
        workflow = Workflow(id="demo", name="Demo", steps=[...])
        router = create_agui_endpoint(workflow)
        app.include_router(router, prefix="/ag-ui/demo")
    """
    effective_registry: PrimitiveRegistry
    if registry is not None:
        effective_registry = registry
    elif deps is not None and deps.registry is not None:
        effective_registry = deps.registry
    else:
        effective_registry = PrimitiveRegistry()
        register_builtins(effective_registry)

    if deps is not None:
        executor = WorkflowExecutor(effective_registry, deps=deps)
    else:
        if provider is not None:
            effective_provider = provider
        else:
            try:
                from beddel_provider_litellm.adapter import LiteLLMAdapter
            except ImportError:
                raise ImportError(
                    "LiteLLM provider not available. Install: pip install beddel[default]"
                ) from None

            effective_provider = LiteLLMAdapter()

        effective_hook_manager: IHookManager
        if hooks is not None:
            effective_hook_manager = hooks
        else:
            from beddel.adapters.hooks import LifecycleHookManager

            effective_hook_manager = LifecycleHookManager()

        fallback_deps = DefaultDependencies(
            llm_provider=effective_provider,
            lifecycle_hooks=effective_hook_manager,
            tracer=tracer,
        )
        executor = WorkflowExecutor(effective_registry, deps=fallback_deps)

    router = APIRouter()

    @router.post("/", response_model=None)
    async def _handle_agui(request: Request) -> EventSourceResponse | JSONResponse:
        """Execute the workflow and stream results as AG-UI SSE events.

        Accepts a JSON body as workflow inputs (optionally in
        ``RunAgentInput`` format with ``thread_id``, ``run_id``,
        ``state``, ``forwarded_props``).  On success, returns an
        ``EventSourceResponse`` streaming AG-UI ``BaseEvent`` instances.
        On error, returns a structured JSON response with ``code``,
        ``message``, and ``details`` fields.
        """
        try:
            body: Any = await request.json()
            raw: dict[str, Any] = body if isinstance(body, dict) else {}
            inputs = _extract_inputs(raw)

            # Extract thread_id and run_id from RunAgentInput format
            raw_thread = raw.get("thread_id")
            thread_id: str | None = raw_thread if isinstance(raw_thread, str) else None
            raw_run = raw.get("run_id")
            run_id: str | None = raw_run if isinstance(raw_run, str) else None

            events = executor.execute_stream(workflow, inputs)
            agui_events = BeddelAGUIAdapter.stream_events(
                events,
                thread_id=thread_id,
                run_id=run_id,
            )
            sse_stream = _agui_sse_stream(agui_events)
            return EventSourceResponse(sse_stream)
        except BeddelError as exc:
            status_code = 422 if isinstance(exc, _CLIENT_ERRORS) else 500
            # Sanitize: exclude provider_error from details and strip
            # upstream exception text from the message to avoid leaking
            # credentials or internal state to HTTP clients.
            safe_details = {k: v for k, v in exc.details.items() if k != "provider_error"}
            safe_message = exc.message.split(":")[0] if status_code == 500 else exc.message
            return JSONResponse(
                status_code=status_code,
                content={
                    "code": exc.code,
                    "message": safe_message,
                    "details": safe_details,
                },
            )
        except Exception:
            logger.exception("Unexpected error in AG-UI workflow handler")
            return JSONResponse(
                status_code=500,
                content={
                    "code": INTERNAL_SERVER_ERROR,
                    "message": "Internal server error",
                    "details": {},
                },
            )

    return router
