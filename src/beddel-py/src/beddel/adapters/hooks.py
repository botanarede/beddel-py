"""Lifecycle hooks adapter — Event-driven callback dispatcher."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from beddel.domain.models import (
        LLMRequest,
        LLMResponse,
        StepDefinition,
        WorkflowDefinition,
    )

logger = logging.getLogger("beddel.adapters.hooks")


class LifecycleHooksAdapter:
    """Adapter implementing ``ILifecycleHook`` with a multi-listener event bus.

    Manages registered callbacks per event name and dispatches them when
    protocol methods are invoked.  Both sync and async callbacks are
    supported — async detection uses ``asyncio.iscoroutinefunction()``.

    All callback exceptions are caught and logged as warnings so that a
    misbehaving listener never crashes the workflow.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., Any]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, event: str, callback: Callable[..., Any]) -> None:
        """Subscribe *callback* to a lifecycle *event*.

        Args:
            event: Event name (e.g. ``"on_workflow_start"``).
            callback: Sync or async callable invoked with event-specific kwargs.
        """
        self._listeners.setdefault(event, []).append(callback)
        logger.debug("register: event=%s callback=%s", event, callback.__name__)

    async def emit(self, event: str, **kwargs: Any) -> None:
        """Dispatch *event* to every registered callback.

        Async callbacks are awaited; sync callbacks are called directly.
        Exceptions are caught per-callback and logged as warnings so that
        remaining listeners still execute.

        Args:
            event: Event name to dispatch.
            **kwargs: Keyword arguments forwarded to each callback.
        """
        for callback in self._listeners.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(**kwargs)
                else:
                    callback(**kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Lifecycle callback error on %s: %s", event, exc)

    # ------------------------------------------------------------------
    # ILifecycleHook protocol methods
    # ------------------------------------------------------------------

    async def on_workflow_start(
        self, workflow: WorkflowDefinition, input_data: dict[str, Any],
    ) -> None:
        """Called when workflow execution begins."""
        await self.emit("on_workflow_start", workflow=workflow, input_data=input_data)

    async def on_step_start(self, step: StepDefinition) -> None:
        """Called before a step executes."""
        await self.emit("on_step_start", step=step)

    async def on_step_end(self, step: StepDefinition, result: Any) -> None:
        """Called after a step completes."""
        await self.emit("on_step_end", step=step, result=result)

    async def on_workflow_end(
        self, workflow: WorkflowDefinition, result: Any,
    ) -> None:
        """Called when workflow execution completes."""
        await self.emit("on_workflow_end", workflow=workflow, result=result)

    async def on_error(self, error: Exception) -> None:
        """Called when an error occurs."""
        await self.emit("on_error", error=error)

    async def on_llm_start(self, request: LLMRequest) -> None:
        """Called before an LLM provider call."""
        await self.emit("on_llm_start", request=request)

    async def on_llm_end(self, request: LLMRequest, response: LLMResponse) -> None:
        """Called after an LLM provider call completes."""
        await self.emit("on_llm_end", request=request, response=response)
