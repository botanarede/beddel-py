"""FastAPI integration — Factory for creating Beddel workflow HTTP handlers.

Provides ``create_beddel_handler()`` which returns an async handler function
suitable for mounting on a FastAPI route.

Requires the ``beddel[fastapi]`` extra::

    pip install beddel[fastapi]
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator as AsyncIteratorABC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import (
    BeddelError,
    ConfigurationError,
    ExecutionError,
    ParseError,
    ProviderError,
)
from beddel.domain.parser import YAMLParser
from beddel.domain.registry import PrimitiveRegistry

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
    from collections.abc import Awaitable, Callable

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


def _build_error_event(exc: Exception) -> dict[str, str]:
    """Build an SSE error event dict from an exception.

    Returns a dict suitable for yielding from an SSE async generator:
    ``{"event": "error", "data": "<json>"}``.
    """
    if isinstance(exc, BeddelError):
        payload: dict[str, Any] = {
            "code": str(exc.code),
            "message": str(exc),
            "details": exc.details,
        }
    else:
        payload = {
            "code": "INTERNAL_ERROR",
            "message": str(exc),
            "details": {},
        }
    return {"event": "error", "data": json.dumps(payload)}


async def _sse_generator(
    executor: WorkflowExecutor,
    workflow_def: WorkflowDefinition,
    request_body: dict[str, Any],
) -> AsyncIteratorABC[dict[str, str]]:
    """Async generator that executes a workflow and yields SSE events.

    Subtasks 3.2–3.5: Execute the workflow, intercept ``AsyncIterator[str]``
    step results, and yield SSE-formatted event dicts.

    Yields:
        Dicts with ``event`` and ``data`` keys consumed by
        ``EventSourceResponse``.
    """
    try:
        result = await executor.execute(workflow_def, request_body)

        # Subtask 3.2: Check if the output is an async iterator (streaming)
        if isinstance(result.output, AsyncIteratorABC):
            logger.debug("streaming async iterator output as SSE chunks")
            async for chunk in result.output:
                # Subtask 3.3: Yield chunk events
                yield {"event": "chunk", "data": str(chunk)}
        else:
            # Non-streaming result from a streaming-declared workflow —
            # emit the full output as a single chunk.
            logger.debug("workflow output is not an async iterator; emitting single chunk")
            yield {
                "event": "chunk",
                "data": json.dumps(
                    result.model_dump(mode="json"),
                ),
            }

        # Subtask 3.4: Done sentinel
        yield {"event": "done", "data": "[DONE]"}

    except (ParseError, ConfigurationError) as exc:
        logger.warning("client error during streaming execution: %s", exc)
        yield _build_error_event(exc)

    except ExecutionError as exc:
        logger.error("execution error during streaming: %s", exc)
        yield _build_error_event(exc)

    except Exception as exc:
        logger.exception("unexpected error during streaming execution")
        yield _build_error_event(exc)


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

    # --- Subtask 2.2: Parse YAML path into WorkflowDefinition ---------------
    workflow_def: WorkflowDefinition
    if isinstance(workflow, str):
        logger.debug("parsing workflow from YAML file: %s", workflow)
        workflow_def = YAMLParser().parse_file(Path(workflow))
    else:
        workflow_def = workflow

    # --- Subtask 2.1: Build WorkflowExecutor from provided/default deps -----
    effective_registry = registry or PrimitiveRegistry()
    executor = WorkflowExecutor(
        registry=effective_registry,
        tracer=tracer,
        hooks=hooks,
    )

    # --- Subtask 2.3 & 2.4: Blocking handler with error mapping -------------
    # --- Subtask 3.1–3.6: SSE streaming handler path -----------------------

    streaming = _is_streaming_workflow(workflow_def)
    if streaming:
        logger.debug("workflow contains streaming step(s) — SSE mode enabled")

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

        # --- Subtask 3.1: Branch on streaming mode --------------------------
        if streaming:
            return EventSourceResponse(
                _sse_generator(executor, workflow_def, request_body),
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


