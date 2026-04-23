"""Unit tests for BeddelAGUIAdapter (Story BC3.1, Task 6)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from ag_ui.core import (
    BaseEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from beddel_ag_ui.adapter import BeddelAGUIAdapter

from beddel.domain.errors import BeddelError
from beddel.domain.models import BeddelEvent, EventType
from beddel.error_codes import INTERNAL_SERVER_ERROR

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: EventType = EventType.WORKFLOW_START,
    step_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> BeddelEvent:
    """Create a BeddelEvent with sensible defaults for testing."""
    return BeddelEvent(
        event_type=event_type,
        step_id=step_id,
        data=data or {},
        timestamp=1000.0,
    )


async def _single_event_stream(
    event: BeddelEvent,
) -> AsyncGenerator[BeddelEvent, None]:
    """Yield a single BeddelEvent."""
    yield event


async def _multi_event_stream(
    events: list[BeddelEvent],
) -> AsyncGenerator[BeddelEvent, None]:
    """Yield multiple BeddelEvents in order."""
    for event in events:
        yield event


async def _empty_stream() -> AsyncGenerator[BeddelEvent, None]:
    """Yield nothing — empty async generator."""
    return
    yield  # noqa: RET504 — makes this a generator


async def _error_stream_beddel() -> AsyncGenerator[BeddelEvent, None]:
    """Yield one event then raise BeddelError."""
    yield _make_event()
    raise BeddelError("BEDDEL-TEST-001", "test error")


async def _error_stream_runtime() -> AsyncGenerator[BeddelEvent, None]:
    """Yield one event then raise RuntimeError."""
    yield _make_event()
    raise RuntimeError("unexpected")


async def _collect(stream: AsyncGenerator[BaseEvent, None]) -> list[BaseEvent]:
    """Drain an async generator into a list."""
    results: list[BaseEvent] = []
    async for event in stream:
        results.append(event)
    return results


# ---------------------------------------------------------------------------
# 6.2 — Single workflow_start → RunStartedEvent
# ---------------------------------------------------------------------------


class TestSingleWorkflowStart:
    """A single workflow_start event maps to RunStartedEvent."""

    async def test_workflow_start_yields_run_started(self) -> None:
        """workflow_start BeddelEvent produces exactly one RunStartedEvent."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_single_event_stream(event)),
        )

        assert len(results) == 1
        assert isinstance(results[0], RunStartedEvent)

    async def test_run_started_has_thread_and_run_ids(self) -> None:
        """RunStartedEvent carries auto-generated thread_id and run_id."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_single_event_stream(event)),
        )

        started = results[0]
        assert isinstance(started, RunStartedEvent)
        assert started.thread_id is not None
        assert started.run_id is not None
        assert len(started.thread_id) > 0
        assert len(started.run_id) > 0


# ---------------------------------------------------------------------------
# 6.3 — Full lifecycle → correct AG-UI event sequence
# ---------------------------------------------------------------------------


class TestFullLifecycle:
    """Full Beddel lifecycle maps to the correct AG-UI event sequence.

    Expected order:
    1. RunStartedEvent        (from workflow_start)
    2. StepStartedEvent       (from step_start)
    3. TextMessageStartEvent  (auto-injected before first text_chunk)
    4. TextMessageContentEvent (from text_chunk)
    5. StepFinishedEvent      (from step_end)
    6. RunFinishedEvent       (from workflow_end)
    7. TextMessageEndEvent    (auto, from else block on normal completion)
    """

    @pytest.fixture()
    def lifecycle_events(self) -> list[BeddelEvent]:
        """Standard lifecycle: start → step → text → step_end → end."""
        return [
            _make_event(event_type=EventType.WORKFLOW_START),
            _make_event(event_type=EventType.STEP_START, step_id="s1"),
            _make_event(
                event_type=EventType.TEXT_CHUNK,
                step_id="s1",
                data={"text": "hello"},
            ),
            _make_event(event_type=EventType.STEP_END, step_id="s1"),
            _make_event(event_type=EventType.WORKFLOW_END),
        ]

    async def test_event_count(self, lifecycle_events: list[BeddelEvent]) -> None:
        """Full lifecycle produces exactly 7 AG-UI events (5 mapped + 2 auto)."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_multi_event_stream(lifecycle_events)),
        )
        assert len(results) == 7

    async def test_event_type_sequence(
        self,
        lifecycle_events: list[BeddelEvent],
    ) -> None:
        """Events are emitted in the correct AG-UI protocol order."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_multi_event_stream(lifecycle_events)),
        )

        expected_types = [
            RunStartedEvent,
            StepStartedEvent,
            TextMessageStartEvent,
            TextMessageContentEvent,
            StepFinishedEvent,
            RunFinishedEvent,
            TextMessageEndEvent,
        ]
        actual_types = [type(e) for e in results]
        assert actual_types == expected_types

    async def test_text_message_start_has_assistant_role(
        self,
        lifecycle_events: list[BeddelEvent],
    ) -> None:
        """Auto-injected TextMessageStartEvent has role='assistant'."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_multi_event_stream(lifecycle_events)),
        )

        start_events = [e for e in results if isinstance(e, TextMessageStartEvent)]
        assert len(start_events) == 1
        assert start_events[0].role == "assistant"

    async def test_text_content_delta(
        self,
        lifecycle_events: list[BeddelEvent],
    ) -> None:
        """TextMessageContentEvent carries the text chunk delta."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_multi_event_stream(lifecycle_events)),
        )

        content_events = [e for e in results if isinstance(e, TextMessageContentEvent)]
        assert len(content_events) == 1
        assert content_events[0].delta == "hello"

    async def test_text_message_bookends_share_message_id(
        self,
        lifecycle_events: list[BeddelEvent],
    ) -> None:
        """Start, content, and end text events share the same message_id."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_multi_event_stream(lifecycle_events)),
        )

        start = next(e for e in results if isinstance(e, TextMessageStartEvent))
        content = next(e for e in results if isinstance(e, TextMessageContentEvent))
        end = next(e for e in results if isinstance(e, TextMessageEndEvent))

        assert start.message_id == content.message_id == end.message_id


# ---------------------------------------------------------------------------
# 6.4 — BeddelError during streaming → RunErrorEvent + RunFinishedEvent
# ---------------------------------------------------------------------------


class TestBeddelErrorDuringStreaming:
    """BeddelError mid-stream emits RunErrorEvent + RunFinishedEvent."""

    async def test_beddel_error_yields_error_and_finished(self) -> None:
        """BeddelError produces RunErrorEvent followed by RunFinishedEvent."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_error_stream_beddel()),
        )

        # First event is RunStartedEvent from the yielded workflow_start
        assert isinstance(results[0], RunStartedEvent)

        # Last two events are error → finished
        assert isinstance(results[-2], RunErrorEvent)
        assert isinstance(results[-1], RunFinishedEvent)

    async def test_beddel_error_code_is_preserved(self) -> None:
        """RunErrorEvent carries the BeddelError's code."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_error_stream_beddel()),
        )

        error_events = [e for e in results if isinstance(e, RunErrorEvent)]
        assert len(error_events) == 1
        assert error_events[0].code == "BEDDEL-TEST-001"

    async def test_beddel_error_message_is_preserved(self) -> None:
        """RunErrorEvent carries the BeddelError's message."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_error_stream_beddel()),
        )

        error_events = [e for e in results if isinstance(e, RunErrorEvent)]
        assert len(error_events) == 1
        assert error_events[0].message == "test error"

    async def test_beddel_error_closes_text_message_if_open(self) -> None:
        """If text was streaming, TextMessageEndEvent precedes RunErrorEvent.

        When a BeddelError occurs after text chunks have been emitted, the
        adapter must close the open text message before emitting error events.
        """

        async def _error_after_text() -> AsyncGenerator[BeddelEvent, None]:
            yield _make_event(event_type=EventType.WORKFLOW_START)
            yield _make_event(
                event_type=EventType.TEXT_CHUNK,
                data={"text": "partial"},
            )
            raise BeddelError("BEDDEL-TEST-002", "mid-text error")

        results = await _collect(
            BeddelAGUIAdapter.stream_events(_error_after_text()),
        )

        # Sequence: RunStarted, TextMessageStart, TextContent,
        #           TextMessageEnd (close), RunError, RunFinished
        type_names = [type(e).__name__ for e in results]
        text_end_idx = type_names.index("TextMessageEndEvent")
        run_error_idx = type_names.index("RunErrorEvent")
        assert text_end_idx < run_error_idx


# ---------------------------------------------------------------------------
# 6.5 — Generic exception → RunErrorEvent with internal code + RunFinishedEvent
# ---------------------------------------------------------------------------


class TestGenericExceptionDuringStreaming:
    """Generic exception mid-stream emits RunErrorEvent with internal code."""

    async def test_runtime_error_yields_error_and_finished(self) -> None:
        """RuntimeError produces RunErrorEvent followed by RunFinishedEvent."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_error_stream_runtime()),
        )

        assert isinstance(results[-2], RunErrorEvent)
        assert isinstance(results[-1], RunFinishedEvent)

    async def test_runtime_error_uses_internal_server_error_code(self) -> None:
        """RunErrorEvent uses INTERNAL_SERVER_ERROR code for generic exceptions."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_error_stream_runtime()),
        )

        error_events = [e for e in results if isinstance(e, RunErrorEvent)]
        assert len(error_events) == 1
        assert error_events[0].code == INTERNAL_SERVER_ERROR

    async def test_runtime_error_message_is_generic(self) -> None:
        """RunErrorEvent message is 'Internal server error' for generic exceptions."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_error_stream_runtime()),
        )

        error_events = [e for e in results if isinstance(e, RunErrorEvent)]
        assert len(error_events) == 1
        assert error_events[0].message == "Internal server error"

    async def test_runtime_error_closes_text_message_if_open(self) -> None:
        """If text was streaming, TextMessageEndEvent precedes RunErrorEvent."""

        async def _runtime_after_text() -> AsyncGenerator[BeddelEvent, None]:
            yield _make_event(event_type=EventType.WORKFLOW_START)
            yield _make_event(
                event_type=EventType.TEXT_CHUNK,
                data={"text": "partial"},
            )
            raise RuntimeError("boom")

        results = await _collect(
            BeddelAGUIAdapter.stream_events(_runtime_after_text()),
        )

        type_names = [type(e).__name__ for e in results]
        text_end_idx = type_names.index("TextMessageEndEvent")
        run_error_idx = type_names.index("RunErrorEvent")
        assert text_end_idx < run_error_idx


# ---------------------------------------------------------------------------
# 6.6 — Empty stream → yields nothing
# ---------------------------------------------------------------------------


class TestEmptyStream:
    """An empty BeddelEvent stream produces zero AG-UI events."""

    async def test_empty_stream_yields_nothing(self) -> None:
        """Empty async generator produces no AG-UI events."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_empty_stream()),
        )
        assert results == []


# ---------------------------------------------------------------------------
# 6.7 — Custom thread_id and run_id are passed through
# ---------------------------------------------------------------------------


class TestCustomIds:
    """Custom thread_id and run_id are passed through to lifecycle events."""

    async def test_custom_thread_id_in_run_started(self) -> None:
        """Custom thread_id appears in RunStartedEvent."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        results = await _collect(
            BeddelAGUIAdapter.stream_events(
                _single_event_stream(event),
                thread_id="custom-thread",
                run_id="custom-run",
            ),
        )

        started = results[0]
        assert isinstance(started, RunStartedEvent)
        assert started.thread_id == "custom-thread"
        assert started.run_id == "custom-run"

    async def test_custom_ids_in_run_finished(self) -> None:
        """Custom thread_id and run_id appear in RunFinishedEvent."""
        events = [
            _make_event(event_type=EventType.WORKFLOW_START),
            _make_event(event_type=EventType.WORKFLOW_END),
        ]
        results = await _collect(
            BeddelAGUIAdapter.stream_events(
                _multi_event_stream(events),
                thread_id="t-42",
                run_id="r-42",
            ),
        )

        finished = next(e for e in results if isinstance(e, RunFinishedEvent))
        assert finished.thread_id == "t-42"
        assert finished.run_id == "r-42"

    async def test_custom_ids_in_error_finished(self) -> None:
        """Custom ids appear in RunFinishedEvent even after errors."""
        results = await _collect(
            BeddelAGUIAdapter.stream_events(
                _error_stream_beddel(),
                thread_id="err-thread",
                run_id="err-run",
            ),
        )

        finished = next(e for e in results if isinstance(e, RunFinishedEvent))
        assert finished.thread_id == "err-thread"
        assert finished.run_id == "err-run"

    async def test_auto_generated_ids_when_not_provided(self) -> None:
        """When no custom ids are provided, UUIDs are auto-generated."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        results = await _collect(
            BeddelAGUIAdapter.stream_events(_single_event_stream(event)),
        )

        started = results[0]
        assert isinstance(started, RunStartedEvent)
        # Auto-generated hex UUIDs are 32 chars
        assert len(started.thread_id) == 32
        assert len(started.run_id) == 32
