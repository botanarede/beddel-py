"""Event-driven execution strategy for Beddel workflows.

Implements trigger-based workflow execution where workflows are invoked by
external events (webhooks, schedules, SSE streams).  The strategy reads
trigger configuration from ``workflow.metadata["trigger"]``, injects a
:class:`~beddel.domain.models.TriggerEvent` into the execution context,
and delegates to the step runner sequentially.

Also provides :class:`WebhookTriggerHandler` for registering FastAPI routes
dynamically without importing FastAPI in the domain layer, and
:class:`ScheduleTriggerHandler` for asyncio-based periodic scheduling.

The strategy satisfies :class:`~beddel.domain.ports.IExecutionStrategy`
via structural subtyping (Protocol conformance).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from beddel.domain.errors import EventDrivenError
from beddel.domain.models import ExecutionContext, TriggerConfig, TriggerEvent, Workflow
from beddel.domain.ports import StepRunner
from beddel.error_codes import EVENT_SCHEDULE_PARSE_FAILED, EVENT_TRIGGER_REGISTRATION_FAILED

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


# Regex for */N cron field syntax
_CRON_EVERY_N = re.compile(r"^\*/(\d+)$")


def _parse_cron_interval(expression: str) -> float:
    """Parse a minimal cron expression and return the interval in seconds.

    Supported format: ``minute hour`` (two fields separated by whitespace).

    Field syntax:
    - ``*`` — wildcard (every unit)
    - ``*/N`` — every *N* units
    - ``0`` — literal zero (used for "at minute 0")

    Examples:
    - ``*/5 *``  → every 5 minutes → 300 s
    - ``0 */2``  → every 2 hours   → 7200 s
    - ``*/15 *`` → every 15 minutes → 900 s

    Args:
        expression: Cron expression string.

    Returns:
        Interval in seconds between runs.

    Raises:
        EventDrivenError: If the expression cannot be parsed.
    """
    parts = expression.strip().split()
    if len(parts) != 2:  # noqa: PLR2004
        raise EventDrivenError(
            EVENT_SCHEDULE_PARSE_FAILED,
            f"Invalid cron expression (expected 2 fields): {expression!r}",
        )

    minute_field, hour_field = parts

    # Parse minute field
    minute_interval: int | None = None
    if minute_field == "*":
        minute_interval = 1  # every minute
    elif _CRON_EVERY_N.match(minute_field):
        n = int(_CRON_EVERY_N.match(minute_field).group(1))  # type: ignore[union-attr]
        if n <= 0 or n > 59:  # noqa: PLR2004
            raise EventDrivenError(
                EVENT_SCHEDULE_PARSE_FAILED,
                f"Invalid minute interval (must be 1-59): {n}",
            )
        minute_interval = n
    elif minute_field == "0":
        minute_interval = None  # literal zero — used with hour field
    else:
        raise EventDrivenError(
            EVENT_SCHEDULE_PARSE_FAILED,
            f"Unsupported minute field: {minute_field!r}",
        )

    # Parse hour field
    hour_interval: int | None = None
    if hour_field == "*":
        hour_interval = None  # no hour constraint
    elif _CRON_EVERY_N.match(hour_field):
        n = int(_CRON_EVERY_N.match(hour_field).group(1))  # type: ignore[union-attr]
        if n <= 0 or n > 23:  # noqa: PLR2004
            raise EventDrivenError(
                EVENT_SCHEDULE_PARSE_FAILED,
                f"Invalid hour interval (must be 1-23): {n}",
            )
        hour_interval = n
    else:
        raise EventDrivenError(
            EVENT_SCHEDULE_PARSE_FAILED,
            f"Unsupported hour field: {hour_field!r}",
        )

    # Calculate total interval in seconds
    if hour_interval is not None:
        # Hour-based: e.g. "0 */2" → every 2 hours
        return float(hour_interval * 3600)
    if minute_interval is not None:
        # Minute-based: e.g. "*/5 *" → every 5 minutes
        return float(minute_interval * 60)

    # Both None means "0 *" → every hour at minute 0
    return 3600.0


class ScheduleTriggerHandler:
    """Asyncio-based scheduler for periodic workflow triggers.

    Supports two modes:

    - **interval**: Fixed number of seconds between invocations.
    - **cron**: Minimal cron expression (``minute hour``) parsed into a
      fixed interval via :func:`_parse_cron_interval`.

    Each tick creates a :class:`~beddel.domain.models.TriggerEvent` with
    ``trigger_type="schedule"`` and an incrementing tick counter.

    Usage::

        handler = ScheduleTriggerHandler()
        await handler.start(interval_seconds=60, callback=my_callback)
        # ... later ...
        handler.stop()
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._tick: int = 0

    async def start(
        self,
        interval_seconds: float,
        callback: Callable[..., Any],
    ) -> None:
        """Start the scheduler with a fixed interval.

        Creates an ``asyncio.Task`` that loops: sleep → create
        :class:`TriggerEvent` → invoke *callback*.

        Args:
            interval_seconds: Seconds between invocations.
            callback: Async callable invoked with a :class:`TriggerEvent`
                on each tick.
        """

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval_seconds)
                self._tick += 1
                now = datetime.now(UTC).isoformat()
                event = TriggerEvent(
                    trigger_type="schedule",
                    payload={"tick": self._tick, "scheduled_at": now},
                    timestamp=now,
                    source=f"schedule:{interval_seconds}s",
                )
                await callback(event)

        self._tick = 0
        self._task = asyncio.create_task(_loop())
        _log.info("Started interval scheduler (every %.2fs)", interval_seconds)

    async def start_cron(
        self,
        expression: str,
        callback: Callable[..., Any],
    ) -> None:
        """Start the scheduler with a cron expression.

        Parses the expression via :func:`_parse_cron_interval` and delegates
        to :meth:`start` with the computed interval.

        Args:
            expression: Minimal cron expression (``minute hour``).
            callback: Async callable invoked with a :class:`TriggerEvent`
                on each tick.

        Raises:
            EventDrivenError: If the expression cannot be parsed.
        """
        interval = _parse_cron_interval(expression)
        await self.start(interval, callback)
        _log.info(
            "Started cron scheduler (%r → %.0fs interval)",
            expression,
            interval,
        )

    def stop(self) -> None:
        """Cancel the running scheduler task."""
        if self._task and not self._task.done():
            self._task.cancel()
            _log.info("Stopped scheduler")

    @property
    def is_running(self) -> bool:
        """Return ``True`` if the scheduler task is active."""
        return self._task is not None and not self._task.done()
