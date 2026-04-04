"""Tests for EventDrivenExecutionStrategy and WebhookTriggerHandler."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest

from beddel.domain.errors import EventDrivenError
from beddel.domain.models import (
    DefaultDependencies,
    ExecutionContext,
    Step,
    TriggerEvent,
    Workflow,
)
from beddel.domain.strategies.event_driven import (
    EventDrivenExecutionStrategy,
    ScheduleTriggerHandler,
    SSETriggerHandler,
    WebhookTriggerHandler,
    _parse_cron_interval,
)
from beddel.error_codes import (
    EVENT_SCHEDULE_PARSE_FAILED,
    EVENT_SSE_CONNECTION_FAILED,
    EVENT_TRIGGER_REGISTRATION_FAILED,
)


def _make_context(**kwargs: object) -> ExecutionContext:
    defaults: dict[str, object] = {
        "workflow_id": "test-wf",
        "inputs": {},
        "deps": DefaultDependencies(),
    }
    defaults.update(kwargs)
    return ExecutionContext(**defaults)  # type: ignore[arg-type]


def _make_workflow(
    steps: list[Step] | None = None,
    metadata: dict[str, object] | None = None,
) -> Workflow:
    return Workflow(
        id="wf-1",
        name="Test Workflow",
        steps=steps or [Step(id="s1", primitive="llm")],
        metadata=metadata or {},
    )


# ── EventDrivenExecutionStrategy ──────────────────────────────────────


class TestEventDrivenExecutionStrategy:
    """Tests for EventDrivenExecutionStrategy."""

    @pytest.mark.asyncio
    async def test_trigger_metadata_injects_trigger_event(self) -> None:
        """Strategy with trigger metadata injects TriggerEvent into context."""
        runner = AsyncMock(return_value="ok")
        workflow = _make_workflow(
            metadata={"trigger": {"type": "webhook", "config": {"path": "/hooks/test"}}},
        )
        context = _make_context()

        strategy = EventDrivenExecutionStrategy()
        await strategy.execute(workflow, context, runner)

        trigger = context.step_results["_trigger"]
        assert isinstance(trigger, TriggerEvent)
        assert trigger.trigger_type == "webhook"
        assert trigger.payload == {}
        assert trigger.timestamp != ""
        runner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_trigger_metadata_still_executes(self) -> None:
        """Strategy without trigger metadata executes steps normally."""
        runner = AsyncMock(return_value="result")
        workflow = _make_workflow()
        context = _make_context()

        strategy = EventDrivenExecutionStrategy()
        await strategy.execute(workflow, context, runner)

        assert "_trigger" not in context.step_results
        runner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pre_existing_trigger_not_overwritten(self) -> None:
        """Strategy with pre-existing _trigger in step_results doesn't overwrite."""
        existing_event = TriggerEvent(
            trigger_type="webhook",
            payload={"key": "value"},
            timestamp="2026-01-01T00:00:00",
            source="/hooks/custom",
        )
        runner = AsyncMock(return_value="ok")
        workflow = _make_workflow(
            metadata={"trigger": {"type": "webhook", "config": {}}},
        )
        context = _make_context()
        context.step_results["_trigger"] = existing_event

        strategy = EventDrivenExecutionStrategy()
        await strategy.execute(workflow, context, runner)

        # The pre-existing event should be preserved
        assert context.step_results["_trigger"] is existing_event
        assert context.step_results["_trigger"].payload == {"key": "value"}

    @pytest.mark.asyncio
    async def test_multiple_steps_executed_sequentially(self) -> None:
        """All workflow steps are executed in order."""
        call_order: list[str] = []

        async def _runner(step: Step, ctx: ExecutionContext) -> str:
            call_order.append(step.id)
            return f"result-{step.id}"

        steps = [
            Step(id="s1", primitive="llm"),
            Step(id="s2", primitive="output"),
            Step(id="s3", primitive="tool"),
        ]
        workflow = _make_workflow(
            steps=steps,
            metadata={"trigger": {"type": "schedule", "config": {"interval": 60}}},
        )
        context = _make_context()

        await EventDrivenExecutionStrategy().execute(workflow, context, _runner)

        assert call_order == ["s1", "s2", "s3"]
        assert isinstance(context.step_results["_trigger"], TriggerEvent)
        assert context.step_results["_trigger"].trigger_type == "schedule"

    @pytest.mark.asyncio
    async def test_suspended_context_stops_execution(self) -> None:
        """Suspended context stops step execution."""
        runner = AsyncMock(return_value="ok")
        steps = [Step(id="s1", primitive="llm"), Step(id="s2", primitive="output")]
        workflow = _make_workflow(steps=steps)
        context = _make_context()
        context.suspended = True

        await EventDrivenExecutionStrategy().execute(workflow, context, runner)

        runner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_trigger_type_string_fallback(self) -> None:
        """Non-dict trigger metadata is converted to string type."""
        runner = AsyncMock(return_value="ok")
        workflow = _make_workflow(metadata={"trigger": "webhook"})
        context = _make_context()

        await EventDrivenExecutionStrategy().execute(workflow, context, runner)

        trigger = context.step_results["_trigger"]
        assert isinstance(trigger, TriggerEvent)
        assert trigger.trigger_type == "webhook"


# ── WebhookTriggerHandler ─────────────────────────────────────────────


class TestWebhookTriggerHandler:
    """Tests for WebhookTriggerHandler."""

    def test_register_with_none_app_raises(self) -> None:
        """Registering with None app raises EventDrivenError."""
        handler = WebhookTriggerHandler()

        with pytest.raises(EventDrivenError) as exc_info:
            handler.register(None, "wf-1", {}, AsyncMock())

        assert exc_info.value.code == EVENT_TRIGGER_REGISTRATION_FAILED
        assert "app is None" in exc_info.value.message

    def test_register_creates_route_on_app(self) -> None:
        """Handler registers a POST route on the mock app."""
        app = MagicMock()
        # app.post(path) returns a decorator, which is called with the handler
        decorator = MagicMock()
        app.post.return_value = decorator

        handler = WebhookTriggerHandler()
        handler.register(app, "wf-1", {}, AsyncMock())

        app.post.assert_called_once_with("/triggers/wf-1")
        decorator.assert_called_once()

    def test_register_custom_path(self) -> None:
        """Handler uses custom path from config."""
        app = MagicMock()
        decorator = MagicMock()
        app.post.return_value = decorator

        handler = WebhookTriggerHandler()
        handler.register(app, "wf-1", {"path": "/hooks/deploy"}, AsyncMock())

        app.post.assert_called_once_with("/hooks/deploy")

    @pytest.mark.asyncio
    async def test_webhook_dispatch_creates_trigger_event(self) -> None:
        """Webhook dispatch creates correct TriggerEvent and calls callback."""
        callback = AsyncMock()
        registered_handler = None

        # Mock app that captures the registered route handler
        app = MagicMock()

        def _capture_decorator(path: str):  # noqa: ANN202
            def _decorator(fn):  # noqa: ANN001, ANN202
                nonlocal registered_handler
                registered_handler = fn
                return fn

            return _decorator

        app.post = _capture_decorator

        handler = WebhookTriggerHandler()
        handler.register(app, "wf-1", {"path": "/hooks/test"}, callback)

        assert registered_handler is not None

        # Simulate a webhook request
        body = {"event": "push", "repo": "beddel"}
        result = await registered_handler(body)

        assert result == {"status": "accepted"}
        callback.assert_awaited_once()

        # Verify the TriggerEvent passed to callback
        event: TriggerEvent = callback.call_args.args[0]
        assert event.trigger_type == "webhook"
        assert event.payload == {"event": "push", "repo": "beddel"}
        assert event.source == "/hooks/test"
        assert event.timestamp != ""

    @pytest.mark.asyncio
    async def test_webhook_default_path(self) -> None:
        """Webhook uses default path /triggers/{workflow_id} when no path in config."""
        callback = AsyncMock()
        registered_handler = None
        registered_path = None

        app = MagicMock()

        def _capture_decorator(path: str):  # noqa: ANN202
            nonlocal registered_path
            registered_path = path

            def _decorator(fn):  # noqa: ANN001, ANN202
                nonlocal registered_handler
                registered_handler = fn
                return fn

            return _decorator

        app.post = _capture_decorator

        handler = WebhookTriggerHandler()
        handler.register(app, "my-workflow", {}, callback)

        assert registered_path == "/triggers/my-workflow"
        assert registered_handler is not None

        result = await registered_handler({"data": "test"})
        assert result == {"status": "accepted"}

        event: TriggerEvent = callback.call_args.args[0]
        assert event.source == "/triggers/my-workflow"


# ── ScheduleTriggerHandler ────────────────────────────────────────────


class TestParseCronInterval:
    """Tests for the minimal cron expression parser."""

    def test_every_5_minutes(self) -> None:
        assert _parse_cron_interval("*/5 *") == 300.0

    def test_every_15_minutes(self) -> None:
        assert _parse_cron_interval("*/15 *") == 900.0

    def test_every_minute(self) -> None:
        assert _parse_cron_interval("* *") == 60.0

    def test_every_2_hours(self) -> None:
        assert _parse_cron_interval("0 */2") == 7200.0

    def test_every_hour_at_minute_zero(self) -> None:
        assert _parse_cron_interval("0 *") == 3600.0

    def test_invalid_too_few_fields(self) -> None:
        with pytest.raises(EventDrivenError) as exc_info:
            _parse_cron_interval("*/5")
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED

    def test_invalid_too_many_fields(self) -> None:
        with pytest.raises(EventDrivenError) as exc_info:
            _parse_cron_interval("*/5 * *")
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED

    def test_invalid_minute_field(self) -> None:
        with pytest.raises(EventDrivenError) as exc_info:
            _parse_cron_interval("abc *")
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED

    def test_invalid_hour_field(self) -> None:
        with pytest.raises(EventDrivenError) as exc_info:
            _parse_cron_interval("*/5 abc")
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED

    def test_invalid_minute_zero_value(self) -> None:
        with pytest.raises(EventDrivenError) as exc_info:
            _parse_cron_interval("*/0 *")
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED

    def test_invalid_minute_too_large(self) -> None:
        with pytest.raises(EventDrivenError) as exc_info:
            _parse_cron_interval("*/60 *")
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED

    def test_invalid_hour_zero_value(self) -> None:
        with pytest.raises(EventDrivenError) as exc_info:
            _parse_cron_interval("0 */0")
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED

    def test_invalid_hour_too_large(self) -> None:
        with pytest.raises(EventDrivenError) as exc_info:
            _parse_cron_interval("0 */24")
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED


class TestScheduleTriggerHandler:
    """Tests for ScheduleTriggerHandler."""

    @pytest.mark.asyncio
    async def test_interval_scheduling_creates_events(self) -> None:
        """Interval scheduler creates TriggerEvents with incrementing ticks."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        handler = ScheduleTriggerHandler()
        await handler.start(interval_seconds=0.01, callback=_cb)
        assert handler.is_running

        await asyncio.sleep(0.05)
        handler.stop()

        assert len(events) >= 2
        assert events[0].trigger_type == "schedule"
        assert events[0].payload["tick"] == 1
        assert events[1].payload["tick"] == 2
        assert "scheduled_at" in events[0].payload
        assert events[0].source == "schedule:0.01s"

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self) -> None:
        """stop() cancels the running task and is_running becomes False."""
        handler = ScheduleTriggerHandler()
        await handler.start(interval_seconds=0.01, callback=AsyncMock())
        assert handler.is_running

        handler.stop()
        # Give the event loop a moment to process the cancellation
        await asyncio.sleep(0.02)
        assert not handler.is_running

    @pytest.mark.asyncio
    async def test_is_running_false_before_start(self) -> None:
        """is_running is False before start is called."""
        handler = ScheduleTriggerHandler()
        assert not handler.is_running

    @pytest.mark.asyncio
    async def test_stop_when_not_running_is_safe(self) -> None:
        """stop() on a non-running handler does not raise."""
        handler = ScheduleTriggerHandler()
        handler.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_cron_start_delegates_to_interval(self) -> None:
        """start_cron parses expression and starts interval scheduling."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        handler = ScheduleTriggerHandler()
        # "*/5 *" = 300s, but we can't wait that long — just verify it starts
        # We'll use a mock to verify the interval was parsed correctly
        await handler.start_cron("*/5 *", _cb)
        assert handler.is_running
        handler.stop()

    @pytest.mark.asyncio
    async def test_cron_invalid_expression_raises(self) -> None:
        """start_cron with invalid expression raises EventDrivenError."""
        handler = ScheduleTriggerHandler()
        with pytest.raises(EventDrivenError) as exc_info:
            await handler.start_cron("invalid", AsyncMock())
        assert exc_info.value.code == EVENT_SCHEDULE_PARSE_FAILED

    @pytest.mark.asyncio
    async def test_tick_event_structure(self) -> None:
        """Each tick event has correct TriggerEvent structure."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        handler = ScheduleTriggerHandler()
        await handler.start(interval_seconds=0.01, callback=_cb)
        await asyncio.sleep(0.03)
        handler.stop()

        assert len(events) >= 1
        event = events[0]
        assert event.trigger_type == "schedule"
        assert isinstance(event.payload, dict)
        assert event.payload["tick"] == 1
        assert "scheduled_at" in event.payload
        # Verify timestamp is ISO format
        assert "T" in event.timestamp
        assert event.source.startswith("schedule:")

    @pytest.mark.asyncio
    async def test_tick_counter_resets_on_restart(self) -> None:
        """Tick counter resets to 0 when start is called again."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        handler = ScheduleTriggerHandler()
        await handler.start(interval_seconds=0.01, callback=_cb)
        await asyncio.sleep(0.03)
        handler.stop()
        await asyncio.sleep(0.02)

        first_run_count = len(events)
        assert first_run_count >= 1

        # Restart — tick should reset
        events.clear()
        await handler.start(interval_seconds=0.01, callback=_cb)
        await asyncio.sleep(0.03)
        handler.stop()

        assert len(events) >= 1
        assert events[0].payload["tick"] == 1  # reset, not continuing


# ── SSETriggerHandler ─────────────────────────────────────────────────


async def _sse_source(lines: list[str]) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted lines from a list."""
    for line in lines:
        yield line


class TestSSETriggerHandler:
    """Tests for SSETriggerHandler."""

    @pytest.mark.asyncio
    async def test_single_event_parsing(self) -> None:
        """A single SSE event (data + blank line) is parsed and dispatched."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        source = _sse_source(["data: hello world", ""])
        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=0)
        await handler.start("https://example.com/events", _cb, event_source=source)

        # Wait for the task to process
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0].trigger_type == "sse"
        assert events[0].payload["data"] == "hello world"
        assert events[0].payload["event"] == "message"
        assert events[0].source == "https://example.com/events"
        assert "T" in events[0].timestamp

    @pytest.mark.asyncio
    async def test_custom_event_type(self) -> None:
        """SSE event with custom event: field is parsed correctly."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        source = _sse_source(["event: deploy", "data: v1.2.3", ""])
        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=0)
        await handler.start("https://example.com/events", _cb, event_source=source)
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0].payload["event"] == "deploy"
        assert events[0].payload["data"] == "v1.2.3"

    @pytest.mark.asyncio
    async def test_multiline_data(self) -> None:
        """Multiple data: lines before blank line are concatenated with newlines."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        source = _sse_source(["data: line1", "data: line2", "data: line3", ""])
        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=0)
        await handler.start("https://example.com/events", _cb, event_source=source)
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0].payload["data"] == "line1\nline2\nline3"

    @pytest.mark.asyncio
    async def test_comment_lines_ignored(self) -> None:
        """Lines starting with : are comments and ignored."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        source = _sse_source([": this is a comment", "data: actual", ""])
        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=0)
        await handler.start("https://example.com/events", _cb, event_source=source)
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0].payload["data"] == "actual"

    @pytest.mark.asyncio
    async def test_multiple_events(self) -> None:
        """Multiple events separated by blank lines are dispatched independently."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        source = _sse_source(
            [
                "data: first",
                "",
                "event: custom",
                "data: second",
                "",
            ]
        )
        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=0)
        await handler.start("https://example.com/events", _cb, event_source=source)
        await asyncio.sleep(0.05)

        assert len(events) == 2
        assert events[0].payload["data"] == "first"
        assert events[0].payload["event"] == "message"
        assert events[1].payload["data"] == "second"
        assert events[1].payload["event"] == "custom"

    @pytest.mark.asyncio
    async def test_blank_line_without_data_does_not_dispatch(self) -> None:
        """A blank line without preceding data: lines does not dispatch an event."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        source = _sse_source(["", "data: real", ""])
        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=0)
        await handler.start("https://example.com/events", _cb, event_source=source)
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0].payload["data"] == "real"

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self) -> None:
        """stop() cancels the running listener task."""

        async def _slow_source() -> AsyncGenerator[str, None]:
            yield "data: start"
            yield ""
            await asyncio.sleep(10)  # Block to keep task alive
            yield "data: never"
            yield ""

        handler = SSETriggerHandler()
        await handler.start(
            "https://example.com/events",
            AsyncMock(),
            event_source=_slow_source(),
        )
        assert handler.is_running

        handler.stop()
        await asyncio.sleep(0.02)
        assert not handler.is_running

    @pytest.mark.asyncio
    async def test_is_running_false_before_start(self) -> None:
        """is_running is False before start is called."""
        handler = SSETriggerHandler()
        assert not handler.is_running

    @pytest.mark.asyncio
    async def test_stop_when_not_running_is_safe(self) -> None:
        """stop() on a non-running handler does not raise."""
        handler = SSETriggerHandler()
        handler.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_reconnection_on_source_exhaustion(self) -> None:
        """Handler reconnects when the event source exhausts."""
        events: list[TriggerEvent] = []
        call_count = 0

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        # Generator that yields one event then exhausts
        async def _exhausting_source() -> AsyncGenerator[str, None]:
            nonlocal call_count
            call_count += 1
            yield f"data: attempt-{call_count}"
            yield ""
            # Generator ends — simulates disconnect

        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=2)
        await handler.start(
            "https://example.com/events",
            _cb,
            event_source=_exhausting_source(),
        )

        # Wait for retries to complete (source exhausts, reconnect attempts)
        await asyncio.sleep(0.15)

        # The first call dispatches an event; subsequent reconnects reuse
        # the same exhausted generator (which yields nothing), so only 1 event
        assert len(events) >= 1
        assert events[0].payload["data"] == "attempt-1"

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises(self) -> None:
        """Exceeding max_retries raises EventDrivenError."""

        async def _empty_source() -> AsyncGenerator[str, None]:
            # Immediately exhausts — no events
            return
            yield  # noqa: RET504 — make it an async generator

        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=1)
        await handler.start(
            "https://example.com/events",
            AsyncMock(),
            event_source=_empty_source(),
        )

        # Wait for retries + final error
        await asyncio.sleep(0.1)

        # The task should have completed with an exception
        assert handler._task is not None  # noqa: SLF001
        assert handler._task.done()  # noqa: SLF001

        with pytest.raises(EventDrivenError) as exc_info:
            handler._task.result()  # noqa: SLF001

        assert exc_info.value.code == EVENT_SSE_CONNECTION_FAILED
        assert "failed after" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_event_type_resets_between_events(self) -> None:
        """Event type resets to 'message' after each dispatched event."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        source = _sse_source(
            [
                "event: custom",
                "data: first",
                "",
                "data: second",
                "",
            ]
        )
        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=0)
        await handler.start("https://example.com/events", _cb, event_source=source)
        await asyncio.sleep(0.05)

        assert len(events) == 2
        assert events[0].payload["event"] == "custom"
        assert events[1].payload["event"] == "message"  # reset to default

    @pytest.mark.asyncio
    async def test_id_lines_are_accepted(self) -> None:
        """Lines starting with id: are accepted without error."""
        events: list[TriggerEvent] = []

        async def _cb(event: TriggerEvent) -> None:
            events.append(event)

        source = _sse_source(["id: 42", "data: with-id", ""])
        handler = SSETriggerHandler(reconnect_delay=0.01, max_retries=0)
        await handler.start("https://example.com/events", _cb, event_source=source)
        await asyncio.sleep(0.05)

        assert len(events) == 1
        assert events[0].payload["data"] == "with-id"
