"""FastAPI integration — one-line workflow-to-endpoint factory.

Provides :func:`create_beddel_handler`, a factory that wires a
:class:`~beddel.domain.models.Workflow` into a FastAPI
:class:`~fastapi.APIRouter` with SSE streaming and structured error
responses.

Example::

    from beddel.domain.models import Workflow
    from beddel.integrations.fastapi import create_beddel_handler

    workflow = Workflow(...)
    router = create_beddel_handler(workflow)
    app.include_router(router, prefix="/my-workflow")

Requires the ``fastapi`` extra: ``pip install beddel[fastapi]``.
"""

from __future__ import annotations

import logging
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
from beddel.integrations.sse import BeddelSSEAdapter
from beddel.primitives import register_builtins

__all__ = ["create_beddel_handler"]

logger = logging.getLogger(__name__)

# Client-error subclasses → HTTP 422
_CLIENT_ERRORS: tuple[type[BeddelError], ...] = (ParseError, ResolveError)


def create_beddel_handler(
    workflow: Workflow,
    *,
    provider: ILLMProvider | None = None,
    registry: PrimitiveRegistry | None = None,
    hooks: IHookManager | None = None,
    tracer: ITracer | None = None,
    deps: DefaultDependencies | None = None,
) -> APIRouter:
    """Create a FastAPI router that exposes a workflow as an SSE endpoint.

    Wires all dependencies (provider, registry, executor) and returns an
    :class:`~fastapi.APIRouter` with a single ``POST /`` endpoint.  The
    endpoint accepts a JSON body as workflow inputs, executes the workflow
    via streaming, and returns an SSE response.

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
        workflow: The workflow definition to expose as an endpoint.
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
        streams workflow events as SSE.

    Example::

        from fastapi import FastAPI
        from beddel.domain.models import Workflow
        from beddel.integrations.fastapi import create_beddel_handler

        app = FastAPI()
        workflow = Workflow(id="demo", name="Demo", steps=[...])
        router = create_beddel_handler(workflow)
        app.include_router(router, prefix="/demo")
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
            from beddel.adapters.litellm_adapter import LiteLLMAdapter

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
        executor = WorkflowExecutor(
            effective_registry,
            deps=fallback_deps,
        )

    router = APIRouter()

    @router.post("/", response_model=None)
    async def _handle_workflow(request: Request) -> EventSourceResponse | JSONResponse:
        """Execute the workflow and stream results as SSE events.

        Accepts a JSON body as workflow inputs.  On success, returns an
        ``EventSourceResponse`` streaming BeddelEvents.  On error, returns
        a structured JSON response with ``code``, ``message``, and
        ``details`` fields.
        """
        try:
            body: Any = await request.json()
            inputs: dict[str, Any] = body if isinstance(body, dict) else {}
            events = executor.execute_stream(workflow, inputs)
            sse_stream = BeddelSSEAdapter.stream_events(events)
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
            logger.exception("Unexpected error in workflow handler")
            return JSONResponse(
                status_code=500,
                content={
                    "code": INTERNAL_SERVER_ERROR,
                    "message": "Internal server error",
                    "details": {},
                },
            )

    return router
