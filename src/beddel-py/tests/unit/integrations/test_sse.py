"""Unit tests for the SSE streaming adapter."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from beddel.domain.models import (
    ErrorCode,
    ExecutionError,
    ExecutionResult,
    ParseError,
)
from beddel.integrations.sse import BeddelSSEAdapter, SSEEvent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_iter(items: list[str]) -> AsyncIterator[str]:
    """Yield items as an async iterator."""
    for item in items:
        yield item


async def _failing_iter(items: list[str], exc: Exception) -> AsyncIterator[str]:
    """Yield items then raise an exception."""
    for item in items:
        yield item
    raise exc


async def _collect(aiter: AsyncIterator[SSEEvent]) -> list[SSEEvent]:
    """Collect all events from an async iterator into a list."""
    events: list[SSEEvent] = []
    async for event in aiter:
        events.append(event)
    return events


# ---------------------------------------------------------------------------
# 5.2 SSEEvent.serialize() — chunk events
# ---------------------------------------------------------------------------


class TestSSEEventSerializeChunk:
    """serialize() produces correct wire format for chunk events."""

    def test_basic_chunk_event(self) -> None:
        """serialize() produces correct wire format for a basic chunk event."""
        event = SSEEvent(event="chunk", data="Hello world")
        result = event.serialize()
        assert result == "event: chunk\ndata: Hello world\n\n"

    def test_done_event(self) -> None:
        """serialize() produces correct wire format for a done event."""
        event = SSEEvent(event="done", data="[DONE]")
        result = event.serialize()
        assert result == "event: done\ndata: [DONE]\n\n"

    def test_error_event(self) -> None:
        """serialize() produces correct wire format for an error event."""
        payload = json.dumps({"code": "INTERNAL_ERROR", "message": "oops"})
        event = SSEEvent(event="error", data=payload)
        result = event.serialize()
        assert result == f"event: error\ndata: {payload}\n\n"

    def test_ends_with_double_newline(self) -> None:
        """serialize() always ends with a blank line (double newline)."""
        event = SSEEvent(event="chunk", data="test")
        assert event.serialize().endswith("\n\n")

    def test_empty_data(self) -> None:
        """serialize() handles empty data string."""
        event = SSEEvent(event="chunk", data="")
        result = event.serialize()
        assert result == "event: chunk\ndata: \n\n"


# ---------------------------------------------------------------------------
# 5.3 SSEEvent.serialize() — optional id and retry fields
# ---------------------------------------------------------------------------


class TestSSEEventSerializeOptionalFields:
    """serialize() includes optional id: and retry: fields when set."""

    def test_with_id_and_retry(self) -> None:
        """serialize() includes id: and retry: fields when both are set."""
        event = SSEEvent(event="chunk", data="Hello", id="42", retry=3000)
        result = event.serialize()
        assert "id: 42\n" in result
        assert "retry: 3000\n" in result
        assert "event: chunk\n" in result
        assert "data: Hello\n" in result
        # Verify field order: id, retry, event, data
        assert result == "id: 42\nretry: 3000\nevent: chunk\ndata: Hello\n\n"

    def test_with_only_id(self) -> None:
        """serialize() includes id: but not retry: when only id is set."""
        event = SSEEvent(event="done", data="[DONE]", id="99")
        result = event.serialize()
        assert "id: 99\n" in result
        assert "retry:" not in result
        assert result == "id: 99\nevent: done\ndata: [DONE]\n\n"

    def test_with_only_retry(self) -> None:
        """serialize() includes retry: but not id: when only retry is set."""
        event = SSEEvent(event="chunk", data="test", retry=5000)
        result = event.serialize()
        assert "retry: 5000\n" in result
        assert "id:" not in result
        assert result == "retry: 5000\nevent: chunk\ndata: test\n\n"

    def test_without_optional_fields(self) -> None:
        """serialize() omits id: and retry: when neither is set."""
        event = SSEEvent(event="chunk", data="plain")
        result = event.serialize()
        assert "id:" not in result
        assert "retry:" not in result

    def test_id_zero_retry_zero(self) -> None:
        """serialize() includes id and retry even when values are zero-like."""
        event = SSEEvent(event="chunk", data="x", id="0", retry=0)
        result = event.serialize()
        assert "id: 0\n" in result
        assert "retry: 0\n" in result


# ---------------------------------------------------------------------------
# 5.4 BeddelSSEAdapter.stream() with AsyncIterator output
# ---------------------------------------------------------------------------


class TestStreamWithAsyncIterator:
    """stream() with AsyncIterator output yields chunk events + done sentinel."""

    async def test_yields_chunk_events_followed_by_done(self) -> None:
        """stream() with AsyncIterator output yields chunk events + done sentinel."""
        chunks = ["Hello", " ", "world"]
        result = ExecutionResult(
            workflow_id="test-123",
            output=_async_iter(chunks),
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream(result))

        # Should have 3 chunk events + 1 done event
        assert len(events) == 4
        for i, chunk in enumerate(chunks):
            assert events[i].event == "chunk"
            assert events[i].data == chunk
        assert events[-1].event == "done"
        assert events[-1].data == "[DONE]"

    async def test_single_chunk_iterator(self) -> None:
        """stream() with single-item iterator yields 1 chunk + done."""
        result = ExecutionResult(
            workflow_id="single-1",
            output=_async_iter(["only"]),
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream(result))

        assert len(events) == 2
        assert events[0].event == "chunk"
        assert events[0].data == "only"
        assert events[1].event == "done"

    async def test_empty_iterator(self) -> None:
        """stream() with empty iterator yields only done sentinel."""
        result = ExecutionResult(
            workflow_id="empty-1",
            output=_async_iter([]),
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream(result))

        assert len(events) == 1
        assert events[0].event == "done"
        assert events[0].data == "[DONE]"


# ---------------------------------------------------------------------------
# 5.5 BeddelSSEAdapter.stream() with non-iterator output
# ---------------------------------------------------------------------------


class TestStreamWithNonIteratorOutput:
    """stream() with non-iterator output yields single chunk + done."""

    async def test_string_output(self) -> None:
        """stream() with string output yields single JSON chunk + done."""
        result = ExecutionResult(
            workflow_id="test-456",
            output="Hello from Beddel!",
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream(result))

        assert len(events) == 2
        assert events[0].event == "chunk"
        # Non-iterator output is JSON-serialized via model_dump
        payload = json.loads(events[0].data)
        assert payload["workflow_id"] == "test-456"
        assert payload["output"] == "Hello from Beddel!"
        assert events[1].event == "done"
        assert events[1].data == "[DONE]"

    async def test_dict_output(self) -> None:
        """stream() with dict output yields single JSON chunk + done."""
        result = ExecutionResult(
            workflow_id="dict-1",
            output={"key": "value"},
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream(result))

        assert len(events) == 2
        assert events[0].event == "chunk"
        payload = json.loads(events[0].data)
        assert payload["output"] == {"key": "value"}
        assert events[1].event == "done"

    async def test_none_output(self) -> None:
        """stream() with None output yields single JSON chunk + done."""
        result = ExecutionResult(
            workflow_id="none-1",
            output=None,
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream(result))

        assert len(events) == 2
        assert events[0].event == "chunk"
        payload = json.loads(events[0].data)
        assert payload["output"] is None
        assert events[1].event == "done"


# ---------------------------------------------------------------------------
# 5.6 BeddelSSEAdapter.stream_iterator()
# ---------------------------------------------------------------------------


class TestStreamIterator:
    """stream_iterator() wraps raw async iterator correctly."""

    async def test_wraps_async_iterator_into_sse_events(self) -> None:
        """stream_iterator() wraps raw async iterator into SSE events."""
        chunks = ["one", "two", "three"]
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_async_iter(chunks)))

        assert len(events) == 4  # 3 chunks + done
        for i, chunk in enumerate(chunks):
            assert events[i].event == "chunk"
            assert events[i].data == chunk
        assert events[-1].event == "done"
        assert events[-1].data == "[DONE]"

    async def test_empty_iterator(self) -> None:
        """stream_iterator() with empty iterator yields only done."""
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_async_iter([])))

        assert len(events) == 1
        assert events[0].event == "done"
        assert events[0].data == "[DONE]"

    async def test_data_is_stringified(self) -> None:
        """stream_iterator() converts each chunk to str via str()."""
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_async_iter(["42"])))

        assert events[0].event == "chunk"
        assert events[0].data == "42"


# ---------------------------------------------------------------------------
# 5.7 Error during streaming yields SSE error event
# ---------------------------------------------------------------------------


class TestErrorDuringStreaming:
    """Exception during iteration yields SSE error event with JSON payload."""

    async def test_runtime_error_yields_error_event(self) -> None:
        """RuntimeError during iteration yields SSE error event."""
        exc = RuntimeError("connection lost")
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter(["ok"], exc)))

        # Should have: 1 chunk ("ok") + 1 error event
        assert len(events) == 2
        assert events[0].event == "chunk"
        assert events[0].data == "ok"
        assert events[1].event == "error"
        error_data = json.loads(events[1].data)
        assert error_data["code"] == "INTERNAL_ERROR"
        assert "connection lost" in error_data["message"]

    async def test_error_on_first_iteration(self) -> None:
        """Error on first iteration yields only error event (no chunks)."""
        exc = RuntimeError("immediate failure")
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        assert events[0].event == "error"
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "INTERNAL_ERROR"
        assert "immediate failure" in error_data["message"]

    async def test_error_via_stream_method(self) -> None:
        """Error during stream() with iterator output yields error event."""
        exc = RuntimeError("stream failure")
        result = ExecutionResult(
            workflow_id="err-stream-1",
            output=_failing_iter(["partial"], exc),
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream(result))

        # Should have: 1 chunk ("partial") + 1 error event
        assert len(events) == 2
        assert events[0].event == "chunk"
        assert events[0].data == "partial"
        assert events[1].event == "error"


# ---------------------------------------------------------------------------
# 5.8 ParseError maps to error event with correct code
# ---------------------------------------------------------------------------


class TestParseErrorMapping:
    """ParseError yields error event with BEDDEL-PARSE-* code."""

    async def test_parse_invalid_yaml(self) -> None:
        """ParseError with PARSE_INVALID_YAML code maps correctly."""
        exc = ParseError(
            "Invalid YAML",
            code=ErrorCode.PARSE_INVALID_YAML,
            details={"line": 5},
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        assert events[0].event == "error"
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "BEDDEL-PARSE-001"
        assert "Invalid YAML" in error_data["message"]
        assert error_data["details"] == {"line": 5}

    async def test_parse_validation_error(self) -> None:
        """ParseError with PARSE_VALIDATION code maps correctly."""
        exc = ParseError(
            "Schema validation failed",
            code=ErrorCode.PARSE_VALIDATION,
            details={"field": "metadata.name"},
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "BEDDEL-PARSE-002"
        assert "Schema validation failed" in error_data["message"]
        assert error_data["details"] == {"field": "metadata.name"}

    async def test_parse_error_after_chunks(self) -> None:
        """ParseError after yielding chunks still produces error event."""
        exc = ParseError(
            "Late parse error",
            code=ErrorCode.PARSE_INVALID_YAML,
            details={},
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter(["a", "b"], exc)))

        assert len(events) == 3  # 2 chunks + 1 error
        assert events[0].event == "chunk"
        assert events[1].event == "chunk"
        assert events[2].event == "error"
        error_data = json.loads(events[2].data)
        assert error_data["code"] == "BEDDEL-PARSE-001"


# ---------------------------------------------------------------------------
# 5.9 ExecutionError maps to error event with correct code
# ---------------------------------------------------------------------------


class TestExecutionErrorMapping:
    """ExecutionError yields error event with BEDDEL-EXEC-* code."""

    async def test_exec_step_failed(self) -> None:
        """ExecutionError with EXEC_STEP_FAILED code maps correctly."""
        exc = ExecutionError(
            "Step failed",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"step_id": "step-1"},
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        assert events[0].event == "error"
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "BEDDEL-EXEC-001"
        assert "Step failed" in error_data["message"]
        assert error_data["details"] == {"step_id": "step-1"}

    async def test_exec_timeout(self) -> None:
        """ExecutionError with EXEC_TIMEOUT code maps correctly."""
        exc = ExecutionError(
            "Workflow timed out",
            code=ErrorCode.EXEC_TIMEOUT,
            details={"timeout_seconds": 300},
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "BEDDEL-EXEC-003"
        assert "Workflow timed out" in error_data["message"]
        assert error_data["details"] == {"timeout_seconds": 300}

    async def test_exec_error_empty_details(self) -> None:
        """ExecutionError with no details produces empty details dict."""
        exc = ExecutionError(
            "No details",
            code=ErrorCode.EXEC_STEP_FAILED,
        )
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        error_data = json.loads(events[0].data)
        assert error_data["details"] == {}


# ---------------------------------------------------------------------------
# 5.10 Generic Exception maps to INTERNAL_ERROR
# ---------------------------------------------------------------------------


class TestGenericExceptionMapping:
    """Generic Exception yields error event with INTERNAL_ERROR code."""

    async def test_value_error(self) -> None:
        """ValueError maps to INTERNAL_ERROR."""
        exc = ValueError("unexpected value")
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        assert events[0].event == "error"
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "INTERNAL_ERROR"
        assert "unexpected value" in error_data["message"]
        assert error_data["details"] == {}

    async def test_type_error(self) -> None:
        """TypeError maps to INTERNAL_ERROR."""
        exc = TypeError("wrong type")
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "INTERNAL_ERROR"
        assert "wrong type" in error_data["message"]
        assert error_data["details"] == {}

    async def test_runtime_error(self) -> None:
        """RuntimeError maps to INTERNAL_ERROR."""
        exc = RuntimeError("something broke")
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "INTERNAL_ERROR"
        assert "something broke" in error_data["message"]

    async def test_key_error(self) -> None:
        """KeyError maps to INTERNAL_ERROR."""
        exc = KeyError("missing_key")
        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_iterator(_failing_iter([], exc)))

        assert len(events) == 1
        error_data = json.loads(events[0].data)
        assert error_data["code"] == "INTERNAL_ERROR"
        assert error_data["details"] == {}


# ---------------------------------------------------------------------------
# 6.1 build_error_event (public API — SSE-001 fix)
# ---------------------------------------------------------------------------


class TestBuildErrorEvent:
    """build_error_event() is now a public function (SSE-001 fix)."""

    def test_importable_as_public(self) -> None:
        """build_error_event can be imported directly from sse module."""
        from beddel.integrations.sse import build_error_event

        assert callable(build_error_event)

    def test_in_all(self) -> None:
        """build_error_event is listed in __all__."""
        from beddel.integrations import sse

        assert "build_error_event" in sse.__all__

    def test_generic_exception(self) -> None:
        """Generic exception produces INTERNAL_ERROR SSE event."""
        from beddel.integrations.sse import build_error_event

        event = build_error_event(RuntimeError("oops"))
        assert event.event == "error"
        error_data = json.loads(event.data)
        assert error_data["code"] == "INTERNAL_ERROR"
        assert "oops" in error_data["message"]
        assert error_data["details"] == {}

    def test_beddel_error(self) -> None:
        """BeddelError produces SSE event with correct code and details."""
        from beddel.integrations.sse import build_error_event

        exc = ExecutionError(
            "Step failed",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"step_id": "s1"},
        )
        event = build_error_event(exc)
        assert event.event == "error"
        error_data = json.loads(event.data)
        assert error_data["code"] == "BEDDEL-EXEC-001"
        assert error_data["details"] == {"step_id": "s1"}


# ---------------------------------------------------------------------------
# 6.1 SSEEvent.serialize() multi-line data (SSE-003 fix)
# ---------------------------------------------------------------------------


class TestSerializeMultiLineData:
    """serialize() splits multi-line data into multiple data: lines (SSE-003 fix)."""

    def test_two_line_data(self) -> None:
        """Two-line data produces two data: lines."""
        event = SSEEvent(event="chunk", data="line1\nline2")
        result = event.serialize()
        assert "data: line1\n" in result
        assert "data: line2\n" in result
        # Should NOT have a single data: line1\nline2
        assert "data: line1\nline2" not in result.replace("data: line1\ndata: line2", "REPLACED")

    def test_three_line_data(self) -> None:
        """Three-line data produces three data: lines."""
        event = SSEEvent(event="chunk", data="a\nb\nc")
        result = event.serialize()
        lines = result.strip().split("\n")
        data_lines = [ln for ln in lines if ln.startswith("data:")]
        assert len(data_lines) == 3
        assert data_lines == ["data: a", "data: b", "data: c"]

    def test_single_line_unchanged(self) -> None:
        """Single-line data still produces one data: line (regression)."""
        event = SSEEvent(event="chunk", data="no newlines here")
        result = event.serialize()
        assert result == "event: chunk\ndata: no newlines here\n\n"

    def test_trailing_newline_in_data(self) -> None:
        """Data ending with newline produces an extra empty data: line."""
        event = SSEEvent(event="chunk", data="text\n")
        result = event.serialize()
        lines = result.strip().split("\n")
        data_lines = [ln for ln in lines if ln.startswith("data:")]
        assert len(data_lines) == 2
        assert data_lines == ["data: text", "data:"]


# ---------------------------------------------------------------------------
# 6.1 BeddelSSEAdapter.stream_events()
# ---------------------------------------------------------------------------


class TestStreamEvents:
    """stream_events() maps BeddelEvent stream to SSEEvent stream."""

    async def test_maps_event_types_correctly(self) -> None:
        """Each BeddelEvent maps to SSEEvent with lowercase event type."""
        from beddel.domain.models import BeddelEvent, BeddelEventType

        async def _event_stream() -> AsyncIterator[BeddelEvent]:
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_START,
                workflow_id="wf-1",
                data={"workflow_name": "test"},
            )
            yield BeddelEvent(
                type=BeddelEventType.STEP_START,
                workflow_id="wf-1",
                step_id="s1",
                data={"step_type": "llm"},
            )
            yield BeddelEvent(
                type=BeddelEventType.STEP_RESULT,
                workflow_id="wf-1",
                step_id="s1",
                data={"output": "hello"},
            )
            yield BeddelEvent(
                type=BeddelEventType.STEP_END,
                workflow_id="wf-1",
                step_id="s1",
            )
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_END,
                workflow_id="wf-1",
                data={"success": True},
            )

        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_events(_event_stream()))

        # 5 BeddelEvents + 1 done sentinel = 6 SSEEvents
        assert len(events) == 6
        assert events[0].event == "workflow_start"
        assert events[1].event == "step_start"
        assert events[2].event == "step_result"
        assert events[3].event == "step_end"
        assert events[4].event == "workflow_end"
        assert events[5].event == "done"
        assert events[5].data == "[DONE]"

    async def test_data_is_json_serialized(self) -> None:
        """BeddelEvent.data is JSON-serialized in SSEEvent.data."""
        from beddel.domain.models import BeddelEvent, BeddelEventType

        async def _event_stream() -> AsyncIterator[BeddelEvent]:
            yield BeddelEvent(
                type=BeddelEventType.STEP_RESULT,
                workflow_id="wf-1",
                step_id="s1",
                data={"output": 42, "success": True},
            )
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_END,
                workflow_id="wf-1",
                data={"success": True},
            )

        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_events(_event_stream()))

        payload = json.loads(events[0].data)
        assert payload == {"output": 42, "success": True}

    async def test_done_sentinel_after_workflow_end(self) -> None:
        """done sentinel is yielded immediately after WORKFLOW_END."""
        from beddel.domain.models import BeddelEvent, BeddelEventType

        async def _event_stream() -> AsyncIterator[BeddelEvent]:
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_START,
                workflow_id="wf-1",
            )
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_END,
                workflow_id="wf-1",
                data={"success": True},
            )

        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_events(_event_stream()))

        assert events[-2].event == "workflow_end"
        assert events[-1].event == "done"
        assert events[-1].data == "[DONE]"

    async def test_error_in_generator_yields_error_event(self) -> None:
        """Exception in the BeddelEvent generator yields SSE error event."""
        from beddel.domain.models import BeddelEvent, BeddelEventType

        async def _failing_stream() -> AsyncIterator[BeddelEvent]:
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_START,
                workflow_id="wf-1",
            )
            raise RuntimeError("generator exploded")

        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_events(_failing_stream()))

        assert len(events) == 2
        assert events[0].event == "workflow_start"
        assert events[1].event == "error"
        error_data = json.loads(events[1].data)
        assert error_data["code"] == "INTERNAL_ERROR"
        assert "generator exploded" in error_data["message"]

    async def test_none_data_serialized_as_null(self) -> None:
        """BeddelEvent with data=None serializes as JSON null."""
        from beddel.domain.models import BeddelEvent, BeddelEventType

        async def _event_stream() -> AsyncIterator[BeddelEvent]:
            yield BeddelEvent(
                type=BeddelEventType.STEP_END,
                workflow_id="wf-1",
                step_id="s1",
                data=None,
            )
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_END,
                workflow_id="wf-1",
                data={"success": True},
            )

        adapter = BeddelSSEAdapter()
        events = await _collect(adapter.stream_events(_event_stream()))

        assert events[0].data == "null"
