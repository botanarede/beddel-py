"""Durable execution strategy with checkpoint-based replay.

Implements the Decorator pattern: wraps any other
:class:`~beddel.domain.ports.IExecutionStrategy` and intercepts the
``step_runner`` callback to add checkpoint/replay logic via an
:class:`~beddel.domain.ports.IEventStore`.

On resume, previously completed steps are skipped and their results
restored from the event store.  New steps execute normally and record
a completion event (containing ``step_id``, ``result``, ``timestamp``)
after each successful execution.

Satisfies :class:`~beddel.domain.ports.IExecutionStrategy` via
structural subtyping (Protocol conformance).
"""

from __future__ import annotations

import time
from typing import Any

from beddel.domain.models import ExecutionContext, Step, Workflow
from beddel.domain.ports import StepRunner


class DurableExecutionStrategy:
    """Execution strategy that adds checkpoint-based replay to any wrapped strategy.

    Uses the Decorator pattern to intercept step execution.  The wrapped
    strategy controls iteration order (sequential, parallel, goal-oriented,
    etc.) while this layer handles checkpoint persistence and replay.

    Args:
        wrapped: The inner execution strategy to delegate to.
        event_store: The event store for persisting step completion events.

    Raises:
        ValueError: If ``wrapped`` or ``event_store`` is ``None``.
    """

    def __init__(self, wrapped: Any, event_store: Any) -> None:
        if wrapped is None:
            raise ValueError("wrapped strategy is required for DurableExecutionStrategy")
        if event_store is None:
            raise ValueError("event_store is required for DurableExecutionStrategy")
        self._wrapped = wrapped
        self._event_store = event_store

    async def execute(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        step_runner: StepRunner,
    ) -> None:
        """Execute the workflow with checkpoint-based replay.

        Loads existing events from the event store, skips steps that
        already have completion events (restoring their results), and
        records new completion events for freshly executed steps.

        Args:
            workflow: The workflow definition containing steps to execute.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.
            step_runner: Callback that executes a single step with full
                lifecycle handling.
        """
        events = await self._event_store.load(context.workflow_id)
        completed: set[str] = {e["step_id"] for e in events}
        event_map: dict[str, dict[str, Any]] = {e["step_id"]: e for e in events}

        async def durable_runner(step: Step, ctx: ExecutionContext) -> Any:
            if step.id in completed:
                stored = event_map[step.id]
                ctx.step_results[step.id] = stored.get("result")
                return ctx.step_results[step.id]

            result = await step_runner(step, ctx)
            await self._event_store.append(
                ctx.workflow_id,
                step.id,
                {"result": ctx.step_results.get(step.id), "timestamp": time.time()},
            )
            return result

        await self._wrapped.execute(workflow, context, durable_runner)
