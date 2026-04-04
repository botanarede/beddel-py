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

from beddel.domain.models import ApprovalResult, Decision, RiskLevel
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
        self._lock = asyncio.Lock()

    async def add_hook(self, hook: ILifecycleHook) -> None:
        """Register a new hook handler.

        Args:
            hook: The lifecycle hook handler to add.
        """
        async with self._lock:
            self._hooks.append(hook)

    async def remove_hook(self, hook: ILifecycleHook) -> None:
        """Unregister a hook handler.

        Silently ignores the call if the hook is not currently registered.

        Args:
            hook: The lifecycle hook handler to remove.
        """
        async with self._lock:
            with contextlib.suppress(ValueError):
                self._hooks.remove(hook)

    async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
        """Dispatch workflow-start event to all registered hooks.

        Args:
            workflow_id: Identifier of the workflow being executed.
            inputs: User-supplied inputs for the workflow run.
        """
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
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
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
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
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
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
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
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
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
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
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
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

    async def on_decision(self, decision: Decision) -> None:
        """Dispatch decision event to all registered hooks.

        Tries the new ``Decision`` dataclass signature first.  If a hook
        still uses the old 3-arg ``(decision, alternatives, rationale)``
        signature, the resulting ``TypeError`` is caught and the call is
        retried with the legacy positional arguments.

        Args:
            decision: The structured :class:`Decision` record.
        """
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_decision):
                    await hook.on_decision(decision)
                else:
                    hook.on_decision(decision)  # type: ignore[unused-coroutine]
            except TypeError:
                # Backward-compatible fallback for old 3-arg hooks
                try:
                    intent = decision.intent
                    options = decision.options
                    reasoning = decision.reasoning
                    if asyncio.iscoroutinefunction(hook.on_decision):
                        await hook.on_decision(intent, options, reasoning)  # type: ignore[call-arg,arg-type]
                    else:
                        hook.on_decision(intent, options, reasoning)  # type: ignore[call-arg,arg-type,unused-coroutine]
                except Exception:
                    logger.warning(
                        "Lifecycle hook %s.on_decision raised (ignored)",
                        type(hook).__name__,
                        exc_info=True,
                    )
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_decision raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_budget_threshold(
        self, workflow_id: str, cumulative_cost: float, threshold: float
    ) -> None:
        """Dispatch budget-threshold event to all registered hooks.

        Args:
            workflow_id: Identifier of the workflow being executed.
            cumulative_cost: The cumulative cost in USD at threshold breach.
            threshold: The degradation threshold value.
        """
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_budget_threshold):
                    await hook.on_budget_threshold(workflow_id, cumulative_cost, threshold)
                else:
                    hook.on_budget_threshold(workflow_id, cumulative_cost, threshold)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_budget_threshold raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_approval_requested(
        self, step_id: str, action: str, risk_level: RiskLevel
    ) -> None:
        """Dispatch approval-requested event to all registered hooks.

        Args:
            step_id: Identifier of the step requiring approval.
            action: Description of the action requiring approval.
            risk_level: The classified risk level of the action.
        """
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_approval_requested):
                    await hook.on_approval_requested(step_id, action, risk_level)
                else:
                    hook.on_approval_requested(step_id, action, risk_level)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_approval_requested raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )

    async def on_approval_received(self, step_id: str, result: ApprovalResult) -> None:
        """Dispatch approval-received event to all registered hooks.

        Args:
            step_id: Identifier of the step that was awaiting approval.
            result: The approval decision.
        """
        async with self._lock:
            hooks = list(self._hooks)
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook.on_approval_received):
                    await hook.on_approval_received(step_id, result)
                else:
                    hook.on_approval_received(step_id, result)  # type: ignore[unused-coroutine]
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.on_approval_received raised (ignored)",
                    type(hook).__name__,
                    exc_info=True,
                )
