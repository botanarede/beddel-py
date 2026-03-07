"""Integration tests for BeddelSSEAdapter (Story 3.3, Task 1)."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.errors import BeddelError
from beddel.domain.models import BeddelEvent, EventType
from beddel.error_codes import INTERNAL_SERVER_ERROR
from beddel.integrations import BeddelSSEAdapter
from beddel.integrations.sse import BeddelSSEAdapter as DirectSSEAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


async def _collect(gen: AsyncGenerator[dict[str, str], None]) -> list[dict[str, str]]:
    """Drain an async generator into a list."""
    results: list[dict[str, str]] = []
    async for item in gen:
        results.append(item)
    return results


def _make_event(
    event_type: EventType = EventType.TEXT_CHUNK,
    step_id: str | None = "step-1",
    data: dict[str, Any] | None = None,
    timestamp: float = 1700000000.0,
) -> BeddelEvent:
    """Create a BeddelEvent with sensible defaults for testing."""
    return BeddelEvent(
        event_type=event_type,
        step_id=step_id,
        data=data if data is not None else {},
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Single-line data serialization
# ---------------------------------------------------------------------------


class TestSingleLineData:
    """Verify SSE dict output for events whose JSON fits on one line."""

    async def test_basic_event_produces_event_and_data_keys(self) -> None:
        """A simple event yields a dict with exactly 'event' and 'data' keys."""
        event = _make_event()
        results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))

        assert len(results) == 1
        sse = results[0]
        assert set(sse.keys()) == {"event", "data"}

    async def test_event_field_uses_event_type_value(self) -> None:
        """The SSE 'event' field must be the EventType string value."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))

        assert results[0]["event"] == "workflow_start"

    async def test_data_field_is_valid_json(self) -> None:
        """The SSE 'data' field must be parseable as JSON."""
        event = _make_event(data={"message": "hello"})
        results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))

        parsed = json.loads(results[0]["data"])
        assert parsed["data"]["message"] == "hello"

    async def test_empty_data_dict_serialization(self) -> None:
        """An event with empty data dict still serializes correctly."""
        event = _make_event(data={})
        results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))

        parsed = json.loads(results[0]["data"])
        assert parsed["data"] == {}

    async def test_step_id_none_for_workflow_events(self) -> None:
        """Workflow-level events with step_id=None serialize correctly."""
        event = _make_event(event_type=EventType.WORKFLOW_START, step_id=None)
        results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))

        parsed = json.loads(results[0]["data"])
        assert parsed["step_id"] is None


# ---------------------------------------------------------------------------
# All EventType values
# ---------------------------------------------------------------------------


class TestAllEventTypes:
    """Every EventType value must produce the correct SSE 'event' field."""

    async def test_all_event_types_produce_correct_sse_event_field(self) -> None:
        """Each EventType enum member maps to its .value in the SSE dict."""
        for et in EventType:
            event = _make_event(event_type=et)
            results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))
            assert results[0]["event"] == et.value, f"Failed for {et}"


# ---------------------------------------------------------------------------
# Multi-line data serialization (W3C SSE compliance)
# ---------------------------------------------------------------------------


class TestMultiLineData:
    """W3C SSE spec: multi-line data must use separate 'data:' lines.

    The adapter joins lines with '\\ndata: ' so sse-starlette emits each
    line with its own 'data:' prefix.
    """

    async def test_multiline_json_uses_data_line_joins(self) -> None:
        """Data containing newlines is joined with '\\ndata: ' for W3C compliance.

        We create an event whose model_dump_json() naturally produces a
        single line (Pydantic compact JSON), then verify the splitting
        logic by testing with data that contains a literal newline in a
        string value — which JSON encodes as \\n (escaped), staying single-line.

        To truly test multi-line splitting, we verify the contract: if the
        serialized JSON were multi-line, each line would be joined with
        '\\ndata: '.
        """
        # Pydantic's model_dump_json() produces compact single-line JSON,
        # so we test the splitting contract by simulating what would happen
        # with multi-line JSON: the adapter splits on \n and joins with \ndata:
        event = _make_event(data={"key": "value"})
        results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))

        data_str = results[0]["data"]
        # Single-line JSON should NOT contain \ndata:
        assert "\ndata: " not in data_str

    async def test_round_trip_json_reconstruction(self) -> None:
        """The data field reconstructs to valid JSON after removing join markers.

        This proves round-trip correctness: serialize → split → join → parse.
        """
        event = _make_event(
            event_type=EventType.STEP_END,
            step_id="step-42",
            data={"result": "success", "tokens": 150},
        )
        results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))

        data_str = results[0]["data"]
        # Undo the multi-line join to reconstruct original JSON
        reconstructed = data_str.replace("\ndata: ", "\n")
        parsed = json.loads(reconstructed)

        assert parsed["event_type"] == "step_end"
        assert parsed["step_id"] == "step-42"
        assert parsed["data"]["result"] == "success"
        assert parsed["data"]["tokens"] == 150

    async def test_actual_multiline_json_splitting(self) -> None:
        """Verify the adapter correctly joins multi-line JSON with data: prefixes.

        Since model_dump_json() produces compact JSON, we patch it to return
        multi-line output to exercise the splitting code path.
        """
        from unittest.mock import patch

        event = _make_event(
            event_type=EventType.STEP_END,
            step_id="s1",
            data={"key": "value"},
        )

        multiline_json = (
            '{\n  "event_type": "step_end",\n  "step_id": "s1",'
            '\n  "data": {"key": "value"},\n  "timestamp": 1700000000.0\n}'
        )

        with patch.object(type(event), "model_dump_json", return_value=multiline_json):
            results = await _collect(BeddelSSEAdapter.stream_events(_single_event_stream(event)))

        assert len(results) == 1
        sse = results[0]
        assert sse["event"] == "step_end"
        # The adapter should have joined lines with \ndata:
        assert "\ndata: " in sse["data"]
        # Verify round-trip: undo the join and parse
        reconstructed = sse["data"].replace("\ndata: ", "\n")
        parsed = json.loads(reconstructed)
        assert parsed["event_type"] == "step_end"
        assert parsed["data"]["key"] == "value"


# ---------------------------------------------------------------------------
# Stream behavior
# ---------------------------------------------------------------------------


class TestStreamBehavior:
    """Verify stream_events handles various stream shapes correctly."""

    async def test_empty_stream_yields_nothing(self) -> None:
        """An empty async generator produces zero SSE dicts."""
        results = await _collect(BeddelSSEAdapter.stream_events(_empty_stream()))
        assert results == []

    async def test_multiple_events_preserve_count_and_order(self) -> None:
        """Multiple events produce the same count of dicts in order."""
        events = [
            _make_event(event_type=EventType.WORKFLOW_START, step_id=None),
            _make_event(event_type=EventType.STEP_START, step_id="s1"),
            _make_event(event_type=EventType.TEXT_CHUNK, step_id="s1"),
            _make_event(event_type=EventType.STEP_END, step_id="s1"),
            _make_event(event_type=EventType.WORKFLOW_END, step_id=None),
        ]
        results = await _collect(BeddelSSEAdapter.stream_events(_multi_event_stream(events)))

        assert len(results) == 5
        assert [r["event"] for r in results] == [
            "workflow_start",
            "step_start",
            "text_chunk",
            "step_end",
            "workflow_end",
        ]


# ---------------------------------------------------------------------------
# Package export
# ---------------------------------------------------------------------------


class TestPackageExport:
    """BeddelSSEAdapter is importable from the integrations package."""

    def test_import_from_integrations_package(self) -> None:
        """BeddelSSEAdapter is re-exported from beddel.integrations."""
        assert BeddelSSEAdapter is DirectSSEAdapter


# ---------------------------------------------------------------------------
# Error-stream helpers (Story 3.6, Task 1)
# ---------------------------------------------------------------------------


async def _error_stream_beddel() -> AsyncGenerator[BeddelEvent, None]:
    """Yield one event then raise BeddelError."""
    yield _make_event(event_type=EventType.STEP_START)
    raise BeddelError("BEDDEL-TEST-001", "test error")


async def _error_stream_runtime() -> AsyncGenerator[BeddelEvent, None]:
    """Yield one event then raise RuntimeError."""
    yield _make_event(event_type=EventType.STEP_START)
    raise RuntimeError("unexpected failure")


# ---------------------------------------------------------------------------
# SSE error protocol (Story 3.6, Task 1)
# ---------------------------------------------------------------------------


class TestSSEErrorProtocol:
    """Verify SSE error event protocol for stream-level exceptions."""

    async def test_beddel_error_emits_error_event_with_exc_code(self) -> None:
        """BeddelError during iteration emits error event with exc.code."""
        results = await _collect(BeddelSSEAdapter.stream_events(_error_stream_beddel()))
        error_events = [r for r in results if r["event"] == "error"]
        assert len(error_events) == 1
        payload = json.loads(error_events[0]["data"])
        assert payload["code"] == "BEDDEL-TEST-001"

    async def test_runtime_error_emits_error_event_with_internal_code(self) -> None:
        """Generic exception emits error event with INTERNAL_SERVER_ERROR code."""
        results = await _collect(BeddelSSEAdapter.stream_events(_error_stream_runtime()))
        error_events = [r for r in results if r["event"] == "error"]
        assert len(error_events) == 1
        payload = json.loads(error_events[0]["data"])
        assert payload["code"] == INTERNAL_SERVER_ERROR

    async def test_done_event_follows_error_event(self) -> None:
        """After error event, a done event is emitted for clean termination."""
        results = await _collect(BeddelSSEAdapter.stream_events(_error_stream_beddel()))
        # Last two events should be error → done
        assert len(results) >= 2
        assert results[-2]["event"] == "error"
        assert results[-1]["event"] == "done"
        assert results[-1]["data"] == ""

    async def test_error_event_data_is_valid_json_with_code_and_message(self) -> None:
        """Error event data is valid JSON containing code and message keys."""
        results = await _collect(BeddelSSEAdapter.stream_events(_error_stream_runtime()))
        error_events = [r for r in results if r["event"] == "error"]
        assert len(error_events) == 1
        payload = json.loads(error_events[0]["data"])
        assert "code" in payload
        assert "message" in payload
        assert isinstance(payload["code"], str)
        assert isinstance(payload["message"], str)

    async def test_normal_stream_no_error_events(self) -> None:
        """A stream without errors produces no error or done events (regression)."""
        events = [
            _make_event(event_type=EventType.WORKFLOW_START, step_id=None),
            _make_event(event_type=EventType.TEXT_CHUNK),
            _make_event(event_type=EventType.WORKFLOW_END, step_id=None),
        ]
        results = await _collect(BeddelSSEAdapter.stream_events(_multi_event_stream(events)))
        event_types = [r["event"] for r in results]
        assert "error" not in event_types
        assert "done" not in event_types
        assert len(results) == 3
