"""Shared test helpers for Beddel SDK primitive tests.

Consolidates ``_make_context`` / ``_make_provider`` variants that were
duplicated across individual primitive test modules.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from beddel.domain.models import DefaultDependencies, ExecutionContext
from beddel.domain.ports import ILLMProvider
from beddel.domain.registry import PrimitiveRegistry


def make_context(
    *,
    workflow_id: str = "wf-test",
    inputs: dict[str, Any] | None = None,
    step_results: dict[str, Any] | None = None,
    step_id: str | None = "step-1",
    metadata: dict[str, Any] | None = None,
    llm_provider: Any | None = None,
    tool_registry: dict[str, Callable[..., Any]] | None = None,
    workflow_loader: Callable[[str], Any] | None = None,
    registry: PrimitiveRegistry | None = None,
) -> ExecutionContext:
    """Build an ``ExecutionContext`` for primitive unit tests.

    This is the consolidated superset of all per-primitive ``_make_context``
    helpers.  Only the parameters you pass are wired; everything else gets
    sensible defaults.

    Args:
        workflow_id: Workflow identifier (default ``"wf-test"``).
        inputs: Workflow-level inputs dict.
        step_results: Results from previous steps.
        step_id: Current step identifier.
        metadata: Arbitrary metadata dict.
        llm_provider: Optional LLM provider (or mock).
        tool_registry: Optional tool-name → callable mapping.
        workflow_loader: Optional callable that loads a ``Workflow`` by id.
        registry: Optional ``PrimitiveRegistry`` instance.

    Returns:
        A configured ``ExecutionContext`` instance.
    """
    has_deps = any(
        arg is not None for arg in (llm_provider, tool_registry, workflow_loader, registry)
    )

    ctx = ExecutionContext(
        workflow_id=workflow_id,
        inputs=inputs or {},
        step_results=step_results or {},
        current_step_id=step_id,
        metadata=metadata or {},
    )

    if has_deps:
        ctx.deps = DefaultDependencies(
            llm_provider=llm_provider,
            tool_registry=tool_registry,
            workflow_loader=workflow_loader,
            registry=registry,
        )

    return ctx


def make_provider(
    *,
    complete_return: dict[str, Any] | None = None,
    stream_chunks: list[str] | None = None,
) -> ILLMProvider:
    """Build a mock ``ILLMProvider`` with configurable return values.

    Args:
        complete_return: Value returned by ``provider.complete()``.
            Defaults to ``{"content": "Hello!"}``.
        stream_chunks: Strings yielded by ``provider.stream()``.
            Defaults to ``["He", "llo", "!"]``.

    Returns:
        A ``MagicMock`` that satisfies the ``ILLMProvider`` interface.
    """
    provider: ILLMProvider = MagicMock(spec=ILLMProvider)
    provider.complete = AsyncMock(  # type: ignore[assignment]
        return_value=complete_return or {"content": "Hello!"},
    )

    async def _stream_gen(*_args: Any, **_kwargs: Any) -> AsyncGenerator[str, None]:
        for chunk in stream_chunks or ["He", "llo", "!"]:
            yield chunk

    provider.stream = MagicMock(side_effect=_stream_gen)  # type: ignore[assignment]
    return provider
