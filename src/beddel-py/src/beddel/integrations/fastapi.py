"""FastAPI integration — Factory for creating Beddel workflow HTTP handlers.

Provides ``create_beddel_handler()`` which returns an async handler function
suitable for mounting on a FastAPI route.

Requires the ``beddel[fastapi]`` extra::

    pip install beddel[fastapi]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import (
    ConfigurationError,
    ExecutionError,
    ParseError,
)
from beddel.domain.parser import YAMLParser
from beddel.domain.registry import PrimitiveRegistry
from beddel.integrations.sse import BeddelSSEAdapter
from beddel.primitives import register_builtins

# ---------------------------------------------------------------------------
# Import guard — fail fast with a helpful message (AC 7)
# ---------------------------------------------------------------------------

try:
    from fastapi import Request  # type: ignore[import-not-found]
    from fastapi.responses import JSONResponse  # type: ignore[import-not-found]
    from sse_starlette.sse import EventSourceResponse  # type: ignore[import-not-found]
except ImportError:
    raise ImportError(
        "beddel[fastapi] extra required: pip install beddel[fastapi]"
    ) from None

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from beddel.domain.models import WorkflowDefinition
    from beddel.domain.ports import ILifecycleHook, ILLMProvider, ITracer

# ---------------------------------------------------------------------------
# Structured logging (subtask 1.3)
# ---------------------------------------------------------------------------

logger = logging.getLogger("beddel.integrations.fastapi")

# ---------------------------------------------------------------------------
# SSE streaming helpers (Task 3)
# ---------------------------------------------------------------------------

_SSE_HEADERS: dict[str, str] = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}


def _is_streaming_workflow(workflow_def: WorkflowDefinition) -> bool:
    """Return ``True`` if any step in the workflow has ``stream: true``."""
    return any(
        step.config.get("stream") is True for step in workflow_def.workflow
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_beddel_handler(
    workflow: WorkflowDefinition | str,
    *,
    provider: ILLMProvider | None = None,
    hooks: list[ILifecycleHook] | None = None,
    tracer: ITracer | None = None,
    registry: PrimitiveRegistry | None = None,
) -> Callable[..., Awaitable[Any]]:
    """Create an async HTTP handler for a Beddel workflow.

    Args:
        workflow: A ``WorkflowDefinition`` instance or a ``str`` path to a
            YAML workflow file.
        provider: Optional LLM provider adapter.
        hooks: Optional lifecycle hooks for observability.
        tracer: Optional tracing adapter (e.g. OpenTelemetry).
        registry: Optional primitive registry. When ``None``, a default
            registry is created.

    Returns:
        An async callable suitable for use as a FastAPI route handler.

    Raises:
        ImportError: If ``fastapi`` or ``sse-starlette`` are not installed.
    """
    logger.debug(
        "creating handler for workflow=%s provider=%s hooks=%d tracer=%s registry=%s",
        workflow if isinstance(workflow, str) else getattr(workflow, "metadata", None),
        type(provider).__name__ if provider else None,
        len(hooks) if hooks else 0,
        type(tracer).__name__ if tracer else None,
        type(registry).__name__ if registry else None,
    )

    # --- Parse YAML path into WorkflowDefinition ----------------------------
    workflow_def: WorkflowDefinition
    if isinstance(workflow, str):
        logger.debug("parsing workflow from YAML file: %s", workflow)
        workflow_def = YAMLParser().parse_file(Path(workflow))
    else:
        workflow_def = workflow

    # --- Build WorkflowExecutor from provided/default deps ------------------
    if registry is None:
        effective_registry = PrimitiveRegistry()
        register_builtins(effective_registry)
    else:
        effective_registry = registry

    # Auto-create a LiteLLM provider when none is supplied
    effective_provider: ILLMProvider | None = provider
    if effective_provider is None:
        from beddel.adapters.litellm import LiteLLMAdapter

        effective_provider = LiteLLMAdapter()
        logger.debug("auto-created LiteLLMAdapter as default provider")

    executor = WorkflowExecutor(
        registry=effective_registry,
        tracer=tracer,
        hooks=hooks,
        provider=effective_provider,
    )

    streaming = _is_streaming_workflow(workflow_def)
    if streaming:
        logger.debug("workflow contains streaming step(s) — SSE mode enabled")

    async def _sse_bridge(
        executor: WorkflowExecutor,
        workflow_def: WorkflowDefinition,
        request_body: dict[str, Any],
    ) -> AsyncIterator[dict[str, str]]:
        """Bridge between WorkflowExecutor.execute_stream() and EventSourceResponse.

        Pipes the ``BeddelEvent`` async generator through
        ``BeddelSSEAdapter.stream_events()`` and converts each ``SSEEvent``
        to the dict format expected by ``EventSourceResponse``.
        """
        adapter = BeddelSSEAdapter()
        try:
            event_stream = executor.execute_stream(workflow_def, request_body)
            async for sse_event in adapter.stream_events(event_stream):
                yield {"event": sse_event.event, "data": sse_event.data}
        except Exception as exc:
            logger.exception("error during SSE streaming execution")
            from beddel.integrations.sse import build_error_event

            error_event = build_error_event(exc)
            yield {"event": error_event.event, "data": error_event.data}

    async def _handler(request: Request) -> JSONResponse | EventSourceResponse:
        try:
            request_body: dict[str, Any] = await request.json()
        except Exception as exc:
            logger.warning("failed to parse request body: %s", exc)
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_REQUEST_BODY",
                        "message": f"Invalid JSON request body: {exc}",
                        "details": {},
                    },
                },
            )

        # --- Branch on streaming mode ---------------------------------------
        if streaming:
            return EventSourceResponse(
                _sse_bridge(executor, workflow_def, request_body),
                headers=_SSE_HEADERS,
            )

        # --- Blocking (non-streaming) path ----------------------------------
        try:
            result = await executor.execute(workflow_def, request_body)
            return JSONResponse(content=result.model_dump(mode="json"))

        except (ParseError, ConfigurationError) as exc:
            logger.warning("client error during workflow execution: %s", exc)
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": str(exc.code),
                        "message": str(exc),
                        "details": exc.details,
                    },
                },
            )

        except ExecutionError as exc:
            # Covers ProviderError and PrimitiveError (subclasses)
            logger.error("execution error during workflow: %s", exc)
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": str(exc.code),
                        "message": str(exc),
                        "details": exc.details,
                    },
                },
            )

        except Exception as exc:
            logger.exception("unexpected error during workflow execution")
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": str(exc),
                        "details": {},
                    },
                },
            )

    return _handler
