"""FastAPI integration — Factory for creating Beddel workflow HTTP handlers.

Provides ``create_beddel_handler()`` which returns an async handler function
suitable for mounting on a FastAPI route.

Requires the ``beddel[fastapi]`` extra::

    pip install beddel[fastapi]
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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
    from beddel.domain.registry import PrimitiveRegistry

# ---------------------------------------------------------------------------
# Structured logging (subtask 1.3)
# ---------------------------------------------------------------------------

logger = logging.getLogger("beddel.integrations.fastapi")

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

    # Placeholder — Tasks 2 and 3 will implement blocking and streaming logic.
    async def _handler(request: Request) -> JSONResponse:
        raise NotImplementedError("handler not yet implemented (see tasks 2–3)")

    return _handler
