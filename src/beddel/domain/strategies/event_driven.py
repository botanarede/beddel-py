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
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import Any

from beddel.domain.errors import EventDrivenError
from beddel.domain.models import ExecutionContext, TriggerConfig, TriggerEvent, Workflow
from beddel.domain.ports import StepRunner
from beddel.error_codes import (
    EVENT_SCHEDULE_PARSE_FAILED,
    EVENT_SSE_CONNECTION_FAILED,
    EVENT_TRIGGER_REGISTRATION_FAILED,
)

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


class SSETriggerHandler:
    """SSE stream listener for event-driven workflow triggers.

    Connects to an external Server-Sent Events endpoint and dispatches
    parsed events as :class:`~beddel.domain.models.TriggerEvent` instances
    to a callback.

    For testability, accepts an optional ``event_source`` async generator
    that yields SSE-formatted lines.  When provided, the handler reads from
    the generator instead of opening a network connection.

    SSE format (line-based):

    - ``data: <payload>`` — event data (multi-line: concatenated with newlines)
    - ``event: <type>`` — event type (default ``"message"``)
    - ``id: <id>`` — event ID (stored but unused)
    - Empty line — delimits events (triggers dispatch)
    - Lines starting with ``:`` — comments (ignored)

    Usage::

        handler = SSETriggerHandler()
        await handler.start("https://example.com/events", callback, event_source=gen)
        # ... later ...
        handler.stop()
    """

    def __init__(
        self,
        *,
        reconnect_delay: float = 5.0,
        max_retries: int = 3,
    ) -> None:
        self._task: asyncio.Task[None] | None = None
        self._reconnect_delay = reconnect_delay
        self._max_retries = max_retries

    async def start(
        self,
        url: str,
        callback: Callable[..., Any],
        *,
        event_source: AsyncGenerator[str, None] | None = None,
    ) -> None:
        """Start listening for SSE events.

        If *event_source* is provided, reads from it (for testing).
        Otherwise, would connect to the URL via ``asyncio.open_connection``
        (production use).

        Args:
            url: The SSE endpoint URL.
            callback: Async callable invoked with a :class:`TriggerEvent`
                for each complete SSE event.
            event_source: Optional async generator yielding SSE-formatted
                lines.  Used for testing without real HTTP connections.
        """

        async def _listen() -> None:
            retries = 0
            while retries <= self._max_retries:
                try:
                    source = event_source if event_source is not None else self._connect(url)
                    await self._consume(source, url, callback)
                    # Source exhausted cleanly — treat as disconnect
                    retries += 1
                    if retries <= self._max_retries:
                        _log.warning(
                            "SSE source disconnected, reconnecting in %.1fs (attempt %d/%d)",
                            self._reconnect_delay,
                            retries,
                            self._max_retries,
                        )
                        await asyncio.sleep(self._reconnect_delay)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    retries += 1
                    if retries <= self._max_retries:
                        _log.warning(
                            "SSE error, reconnecting in %.1fs (attempt %d/%d)",
                            self._reconnect_delay,
                            retries,
                            self._max_retries,
                            exc_info=True,
                        )
                        await asyncio.sleep(self._reconnect_delay)

            # All retries exhausted
            raise EventDrivenError(
                EVENT_SSE_CONNECTION_FAILED,
                f"SSE connection failed after {self._max_retries} retries: {url}",
            )

        self._task = asyncio.create_task(_listen())
        _log.info("Started SSE listener for %s", url)

    @staticmethod
    async def _connect(url: str) -> AsyncGenerator[str, None]:
        """Connect to an SSE endpoint via ``asyncio.open_connection``.

        Parses the URL to extract host and port, sends a minimal HTTP GET
        request, and yields response lines.

        Args:
            url: The SSE endpoint URL (``http://`` or ``https://``).

        Yields:
            Individual lines from the SSE stream.
        """
        # Minimal URL parsing for host:port
        stripped = url.split("://", 1)[-1]
        path_sep = stripped.find("/")
        if path_sep == -1:
            host_port = stripped
            path = "/"
        else:
            host_port = stripped[:path_sep]
            path = stripped[path_sep:]

        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 443 if url.startswith("https") else 80

        ssl_ctx = url.startswith("https") or None
        reader, writer = await asyncio.open_connection(host, port, ssl=ssl_ctx)

        # Send HTTP GET request
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Accept: text/event-stream\r\n"
            f"Cache-Control: no-cache\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        )
        writer.write(request.encode())
        await writer.drain()

        # Skip HTTP response headers
        while True:
            header_line = await reader.readline()
            if header_line in (b"\r\n", b"\n", b""):
                break

        # Yield body lines
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                yield raw.decode("utf-8", errors="replace").rstrip("\r\n")
        finally:
            writer.close()

    @staticmethod
    async def _consume(
        source: AsyncGenerator[str, None],
        url: str,
        callback: Callable[..., Any],
    ) -> None:
        """Consume SSE lines from *source* and dispatch complete events.

        Args:
            source: Async generator yielding SSE-formatted lines.
            url: The SSE endpoint URL (used as ``TriggerEvent.source``).
            callback: Async callable invoked with each parsed
                :class:`TriggerEvent`.
        """
        data_lines: list[str] = []
        event_type: str = "message"

        async for line in source:
            if line.startswith(":"):
                # Comment — ignore
                continue

            if line == "":
                # Blank line — dispatch accumulated event
                if data_lines:
                    event = TriggerEvent(
                        trigger_type="sse",
                        payload={
                            "data": "\n".join(data_lines),
                            "event": event_type,
                        },
                        timestamp=datetime.now(UTC).isoformat(),
                        source=url,
                    )
                    await callback(event)
                # Reset accumulators
                data_lines = []
                event_type = "message"
                continue

            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip(" "))
            elif line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("id:"):
                pass  # Store but don't use

    def stop(self) -> None:
        """Cancel the listener task."""
        if self._task and not self._task.done():
            self._task.cancel()
            _log.info("Stopped SSE listener")

    @property
    def is_running(self) -> bool:
        """Return ``True`` if the listener task is active."""
        return self._task is not None and not self._task.done()
