"""Port interfaces — Protocol definitions for hexagonal architecture boundaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from beddel.domain.models import (
        LLMRequest,
        LLMResponse,
        StepDefinition,
        WorkflowDefinition,
    )


@runtime_checkable
class ILLMProvider(Protocol):
    """Port for LLM provider adapters (e.g. LiteLLM)."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute a single LLM completion request."""
        ...

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream LLM completion chunks."""
        ...


@runtime_checkable
class ITracer(Protocol):
    """Port for observability/tracing adapters (e.g. OpenTelemetry)."""

    def start_workflow_span(self, workflow: WorkflowDefinition) -> Any:
        """Start a span for workflow execution. Returns a span handle."""
        ...

    def start_step_span(self, step: StepDefinition, parent: Any) -> Any:
        """Start a span for step execution. Returns a span handle."""
        ...

    def end_span(self, span: Any, *, error: str | None = None) -> None:
        """End a span, optionally recording an error."""
        ...


@runtime_checkable
class ILifecycleHook(Protocol):
    """Port for lifecycle event hooks."""

    async def on_workflow_start(
        self, workflow: WorkflowDefinition, input_data: dict[str, Any],
    ) -> None:
        """Called when workflow execution begins."""
        ...

    async def on_step_start(self, step: StepDefinition) -> None:
        """Called before a step executes."""
        ...

    async def on_step_end(self, step: StepDefinition, result: Any) -> None:
        """Called after a step completes."""
        ...

    async def on_workflow_end(
        self, workflow: WorkflowDefinition, result: Any,
    ) -> None:
        """Called when workflow execution completes."""
        ...

    async def on_error(self, error: Exception) -> None:
        """Called when an error occurs."""
        ...
