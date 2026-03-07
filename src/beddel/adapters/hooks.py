"""Lifecycle hook manager adapter — fan-out dispatcher for workflow hooks.

Implements :class:`~beddel.domain.ports.IHookManager` and dispatches
each lifecycle event to all registered hook handlers.  Each dispatch is
wrapped in ``try/except`` so a misbehaving hook never breaks workflow
execution.

Supports both sync and async hook handlers — sync handlers are detected
via :func:`asyncio.iscoroutinefunction` and called without ``await``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from beddel.domain.ports import IHookManager, ILifecycleHook

logger = logging.getLogger(__name__)

__all__ = ["LifecycleHookManager"]


class LifecycleHookManager(IHookManager):
    """Adapter that dispatches lifecycle events to multiple registered hooks.

    Implements :class:`~beddel.domain.ports.IHookManager` and fans out
    each event to all registered hook handlers.  Each dispatch is wrapped
    in ``try/except`` — a misbehaving hook never breaks workflow execution.

    Supports both sync and async handlers: sync handlers are detected via
    :func:`asyncio.iscoroutinefunction` and called directly (without
    ``await``); async handlers are awaited normally.

    Args:
        hooks: Optional initial list of hook handlers to register.

    Example::

        manager = LifecycleHookManager([my_hook])
        await manager.add_hook(another_hook)
        await manager.on_workflow_start("wf-1", {"key": "value"})
    """

    def __init__(self, hooks: list[ILifecycleHook] | None = None) -> None:
        self._hooks: list[ILifecycleHook] = list(hooks) if hooks else []

    async def add_hook(self, hook: ILifecycleHook) -> None:
        """Register a new hook handler.

        Args:
            hook: The lifecycle hook handler to add.
        """
        self._hooks.append(hook)

    async def remove_hook(self, hook: ILifecycleHook) -> None:
        """Unregister a hook handler.

        Silently ignores the call if the hook is not currently registered.

        Args:
            hook: The lifecycle hook handler to remove.
        """
        with contextlib.suppress(ValueError):
            self._hooks.remove(hook)

    async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
        """Dispatch workflow-start event to all registered hooks.

        Args:
            workflow_id: Identifier of the workflow being executed.
            inputs: User-supplied inputs for the workflow run.
        """
        for hook in self._hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_workflow_start):
                    await hook.on_workflow_start(workflow_id, inputs)
                else:
                    hook.on_workflow_start(workflow_id, inputs)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_workflow_start raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
        """Dispatch workflow-end event to all registered hooks.

        Args:
            workflow_id: Identifier of the workflow that completed.
            result: The final workflow result dict.
        """
        for hook in self._hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_workflow_end):
                    await hook.on_workflow_end(workflow_id, result)
                else:
                    hook.on_workflow_end(workflow_id, result)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_workflow_end raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_step_start(self, step_id: str, primitive: str) -> None:
        """Dispatch step-start event to all registered hooks.

        Args:
            step_id: Identifier of the step about to execute.
            primitive: Name of the primitive being invoked.
        """
        for hook in self._hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_step_start):
                    await hook.on_step_start(step_id, primitive)
                else:
                    hook.on_step_start(step_id, primitive)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_step_start raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_step_end(self, step_id: str, result: Any) -> None:
        """Dispatch step-end event to all registered hooks.

        Args:
            step_id: Identifier of the step that completed.
            result: The step's return value.
        """
        for hook in self._hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_step_end):
                    await hook.on_step_end(step_id, result)
                else:
                    hook.on_step_end(step_id, result)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_step_end raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_error(self, step_id: str, error: Exception) -> None:
        """Dispatch error event to all registered hooks.

        Args:
            step_id: Identifier of the step that failed.
            error: The exception that was raised.
        """
        for hook in self._hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_error):
                    await hook.on_error(step_id, error)
                else:
                    hook.on_error(step_id, error)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_error raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_retry(self, step_id: str, attempt: int, error: Exception) -> None:
        """Dispatch retry event to all registered hooks.

        Args:
            step_id: Identifier of the step being retried.
            attempt: The retry attempt number (1-based).
            error: The exception that triggered the retry.
        """
        for hook in self._hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_retry):
                    await hook.on_retry(step_id, attempt, error)
                else:
                    hook.on_retry(step_id, attempt, error)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_retry raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_decision(self, decision: str, alternatives: list[str], rationale: str) -> None:
        """Dispatch decision event to all registered hooks.

        Args:
            decision: The decision that was made.
            alternatives: Alternative options that were considered.
            rationale: Explanation for why this decision was chosen.
        """
        for hook in self._hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_decision):
                    await hook.on_decision(decision, alternatives, rationale)
                else:
                    hook.on_decision(decision, alternatives, rationale)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_decision raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )
