"""Event-driven execution strategy for Beddel workflows.

Implements trigger-based workflow execution where workflows are invoked by
external events (webhooks, schedules, SSE streams).  The strategy reads
trigger configuration from ``workflow.metadata["trigger"]``, injects a
:class:`~beddel.domain.models.TriggerEvent` into the execution context,
and delegates to the step runner sequentially.

Also provides :class:`WebhookTriggerHandler` for registering FastAPI routes
dynamically without importing FastAPI in the domain layer.

The strategy satisfies :class:`~beddel.domain.ports.IExecutionStrategy`
via structural subtyping (Protocol conformance).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from beddel.domain.errors import EventDrivenError
from beddel.domain.models import ExecutionContext, TriggerConfig, TriggerEvent, Workflow
from beddel.domain.ports import StepRunner
from beddel.error_codes import EVENT_TRIGGER_REGISTRATION_FAILED

_log = logging.getLogger(__name__)


class EventDrivenExecutionStrategy:
    """Execution strategy that injects trigger context before sequential step execution.

    Reads ``workflow.metadata["trigger"]`` to build a :class:`TriggerConfig`.
    If a trigger config exists and no ``_trigger`` key is already present in
    ``context.step_results``, a default :class:`TriggerEvent` is injected so
    downstream steps can reference trigger data via ``$stepResult._trigger``.

    When a trigger handler (e.g. :class:`WebhookTriggerHandler`) has already
    set ``_trigger`` in the context, the strategy leaves it as-is.

    Steps are then executed sequentially, identical to ``SequentialStrategy``,
    checking ``context.suspended`` before each step.
    """

    async def execute(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        step_runner: StepRunner,
    ) -> None:
        """Execute workflow steps with trigger context injection.

        Args:
            workflow: The workflow definition containing steps and trigger metadata.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.
            step_runner: :data:`StepRunner` callback that executes a single
                step with full lifecycle handling.
        """
        # 1. Read trigger config from workflow metadata
        trigger_raw = workflow.metadata.get("trigger")

        if trigger_raw is not None:
            # Build TriggerConfig from metadata dict
            if isinstance(trigger_raw, dict):
                trigger_config = TriggerConfig(
                    type=trigger_raw.get("type", ""),
                    config=trigger_raw.get("config", {}),
                    workflow_id=workflow.id,
                )
            else:
                trigger_config = TriggerConfig(
                    type=str(trigger_raw),
                    workflow_id=workflow.id,
                )

            # 2. Inject TriggerEvent if not already set by a handler
            if "_trigger" not in context.step_results:
                event = TriggerEvent(
                    trigger_type=trigger_config.type,
                    payload={},
                    timestamp=datetime.now(UTC).isoformat(),
                    source="",
                )
                context.step_results["_trigger"] = event
                _log.debug(
                    "Injected default TriggerEvent for workflow %s (type=%s)",
                    workflow.id,
                    trigger_config.type,
                )

        # 3. Execute steps sequentially (same as SequentialStrategy)
        for step in workflow.steps:
            if context.suspended:
                break
            await step_runner(step, context)


class WebhookTriggerHandler:
    """Registers FastAPI webhook routes dynamically for trigger-based workflows.

    The ``app`` parameter is typed as :class:`Any` to avoid importing FastAPI
    in the domain layer, preserving hexagonal architecture boundaries.

    Usage::

        handler = WebhookTriggerHandler()
        handler.register(app, "my-workflow", {"path": "/hooks/deploy"}, callback)
    """

    def register(
        self,
        app: Any,
        workflow_id: str,
        config: dict[str, Any],
        callback: Callable[..., Any],
    ) -> None:
        """Register a POST route on the FastAPI app for webhook triggers.

        Args:
            app: The FastAPI application instance (typed as ``Any``).
            workflow_id: Identifier of the workflow to trigger.
            config: Trigger configuration dict. Supports ``path`` key for
                custom route path (defaults to ``/triggers/{workflow_id}``).
            callback: Async callable invoked with a :class:`TriggerEvent`
                when the webhook receives a request.

        Raises:
            EventDrivenError: If ``app`` is ``None``.
        """
        if app is None:
            raise EventDrivenError(
                EVENT_TRIGGER_REGISTRATION_FAILED,
                "Cannot register webhook: app is None",
            )

        path = config.get("path", f"/triggers/{workflow_id}")

        async def _webhook_handler(body: dict[str, Any]) -> dict[str, str]:
            event = TriggerEvent(
                trigger_type="webhook",
                payload=body,
                timestamp=datetime.now(UTC).isoformat(),
                source=path,
            )
            await callback(event)
            return {"status": "accepted"}

        # Register route dynamically using app.post() decorator pattern
        app.post(path)(_webhook_handler)

        _log.info(
            "Registered webhook trigger for workflow %s at %s",
            workflow_id,
            path,
        )
