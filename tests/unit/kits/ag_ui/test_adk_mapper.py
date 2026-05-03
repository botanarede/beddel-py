"""Unit tests for ADK Event → BeddelEvent mapper (Story GTW-BC.10, Task 3).

Tests cover:
- Tool call (functionCall) → STEP_START
- Tool response (functionResponse) → STEP_END
- Text streaming → TEXT_CHUNK
- Empty parts handling
- Error handling (malformed events)
- Synthetic WORKFLOW_START / WORKFLOW_END bookends
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from beddel_ag_ui.adk_mapper import map_adk_events

from beddel.domain.models import BeddelEvent, EventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _adk_stream(
    events: list[dict[str, Any]],
) -> AsyncGenerator[dict[str, Any], None]:
    """Convert a list of ADK event dicts into an async generator."""
    for event in events:
        yield event


async def _collect(
    gen: AsyncGenerator[BeddelEvent, None],
) -> list[BeddelEvent]:
    """Drain an async generator into a list."""
    results: list[BeddelEvent] = []
    async for event in gen:
        results.append(event)
    return results


def _make_function_call_event(
    name: str = "research_pipeline",
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an ADK event dict with a functionCall part."""
    return {
        "content": {
            "role": "model",
            "parts": [
                {
                    "functionCall": {
                        "name": name,
                        "args": args or {},
                    },
                },
            ],
        },
    }


def _make_function_response_event(
    name: str = "research_pipeline",
    response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an ADK event dict with a functionResponse part."""
    return {
        "content": {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": name,
                        "response": response or {},
                    },
                },
            ],
        },
    }


def _make_text_event(text: str = "Hello world") -> dict[str, Any]:
    """Build an ADK event dict with a text part."""
    return {
        "content": {
            "role": "model",
            "parts": [{"text": text}],
        },
    }


# ---------------------------------------------------------------------------
# Tool call + response mapping
# ---------------------------------------------------------------------------


class TestToolCallMapping:
    """functionCall parts map to STEP_START events."""

    async def test_function_call_yields_step_start(self) -> None:
        """A functionCall part produces a STEP_START BeddelEvent."""
        adk_events = [_make_function_call_event("research_pipeline", {"topic": "AI"})]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        step_starts = [e for e in results if e.event_type == EventType.STEP_START]
        assert len(step_starts) == 1
        assert step_starts[0].step_id == "research_pipeline"
        assert step_starts[0].data == {"args": {"topic": "AI"}}

    async def test_function_response_yields_step_end(self) -> None:
        """A functionResponse part produces a STEP_END BeddelEvent."""
        adk_events = [
            _make_function_response_event(
                "research_pipeline",
                {"result": "AI is transformative"},
            ),
        ]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        step_ends = [e for e in results if e.event_type == EventType.STEP_END]
        assert len(step_ends) == 1
        assert step_ends[0].step_id == "research_pipeline"
        assert step_ends[0].data == {"response": {"result": "AI is transformative"}}

    async def test_tool_call_and_response_sequence(self) -> None:
        """A functionCall followed by functionResponse yields STEP_START then STEP_END."""
        adk_events = [
            _make_function_call_event("email_classifier", {"email": "Hello"}),
            _make_function_response_event(
                "email_classifier",
                {"intent": "greeting"},
            ),
        ]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        # Filter out synthetic bookends
        core_events = [
            e
            for e in results
            if e.event_type not in (EventType.WORKFLOW_START, EventType.WORKFLOW_END)
        ]
        assert len(core_events) == 2
        assert core_events[0].event_type == EventType.STEP_START
        assert core_events[0].step_id == "email_classifier"
        assert core_events[1].event_type == EventType.STEP_END
        assert core_events[1].step_id == "email_classifier"

    async def test_function_call_missing_name_defaults_to_unknown(self) -> None:
        """A functionCall without a name field defaults step_id to 'unknown'."""
        adk_events = [
            {
                "content": {
                    "role": "model",
                    "parts": [{"functionCall": {"args": {"x": 1}}}],
                },
            },
        ]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        step_starts = [e for e in results if e.event_type == EventType.STEP_START]
        assert len(step_starts) == 1
        assert step_starts[0].step_id == "unknown"

    async def test_function_response_missing_name_defaults_to_unknown(self) -> None:
        """A functionResponse without a name field defaults step_id to 'unknown'."""
        adk_events = [
            {
                "content": {
                    "role": "user",
                    "parts": [{"functionResponse": {"response": {}}}],
                },
            },
        ]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        step_ends = [e for e in results if e.event_type == EventType.STEP_END]
        assert len(step_ends) == 1
        assert step_ends[0].step_id == "unknown"


# ---------------------------------------------------------------------------
# Text streaming mapping
# ---------------------------------------------------------------------------


class TestTextStreamingMapping:
    """text parts map to TEXT_CHUNK events."""

    async def test_text_part_yields_text_chunk(self) -> None:
        """A text part produces a TEXT_CHUNK BeddelEvent."""
        adk_events = [_make_text_event("Here is the summary")]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        text_chunks = [e for e in results if e.event_type == EventType.TEXT_CHUNK]
        assert len(text_chunks) == 1
        assert text_chunks[0].data == {"text": "Here is the summary"}

    async def test_multiple_text_events_yield_multiple_chunks(self) -> None:
        """Multiple text events produce multiple TEXT_CHUNK events."""
        adk_events = [
            _make_text_event("Part 1"),
            _make_text_event("Part 2"),
            _make_text_event("Part 3"),
        ]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        text_chunks = [e for e in results if e.event_type == EventType.TEXT_CHUNK]
        assert len(text_chunks) == 3
        assert [c.data["text"] for c in text_chunks] == [
            "Part 1",
            "Part 2",
            "Part 3",
        ]

    async def test_text_chunk_has_no_step_id(self) -> None:
        """TEXT_CHUNK events have step_id=None."""
        adk_events = [_make_text_event("hello")]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        text_chunks = [e for e in results if e.event_type == EventType.TEXT_CHUNK]
        assert text_chunks[0].step_id is None


# ---------------------------------------------------------------------------
# Empty parts handling
# ---------------------------------------------------------------------------


class TestEmptyPartsHandling:
    """Events with empty or missing parts are handled gracefully."""

    async def test_empty_parts_list_yields_no_domain_events(self) -> None:
        """An event with an empty parts list produces no domain events."""
        adk_events = [{"content": {"role": "model", "parts": []}}]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        # Only synthetic bookends
        assert len(results) == 2
        assert results[0].event_type == EventType.WORKFLOW_START
        assert results[1].event_type == EventType.WORKFLOW_END

    async def test_missing_parts_key_yields_no_domain_events(self) -> None:
        """An event without a parts key produces no domain events."""
        adk_events = [{"content": {"role": "model"}}]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        assert len(results) == 2
        assert results[0].event_type == EventType.WORKFLOW_START
        assert results[1].event_type == EventType.WORKFLOW_END

    async def test_missing_content_key_yields_no_domain_events(self) -> None:
        """An event without a content key produces no domain events."""
        adk_events = [{}]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        assert len(results) == 2
        assert results[0].event_type == EventType.WORKFLOW_START
        assert results[1].event_type == EventType.WORKFLOW_END

    async def test_empty_text_is_skipped(self) -> None:
        """A text part with an empty string is skipped."""
        adk_events = [_make_text_event("")]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        text_chunks = [e for e in results if e.event_type == EventType.TEXT_CHUNK]
        assert len(text_chunks) == 0

    async def test_empty_stream_yields_only_bookends(self) -> None:
        """An empty ADK event stream yields only WORKFLOW_START and WORKFLOW_END."""
        results = await _collect(map_adk_events(_adk_stream([])))

        assert len(results) == 2
        assert results[0].event_type == EventType.WORKFLOW_START
        assert results[1].event_type == EventType.WORKFLOW_END

    async def test_unrecognised_part_type_is_skipped(self) -> None:
        """A part with an unrecognised key is silently skipped."""
        adk_events = [
            {
                "content": {
                    "role": "model",
                    "parts": [{"unknownPartType": {"data": "ignored"}}],
                },
            },
        ]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        # Only synthetic bookends
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Errors in the ADK event stream propagate correctly."""

    async def test_error_in_stream_propagates(self) -> None:
        """An exception in the ADK event stream propagates to the caller."""

        async def _error_stream() -> AsyncGenerator[dict[str, Any], None]:
            yield _make_text_event("before error")
            raise RuntimeError("ADK stream failed")

        with pytest.raises(RuntimeError, match="ADK stream failed"):
            await _collect(map_adk_events(_error_stream()))

    async def test_workflow_start_emitted_before_error(self) -> None:
        """WORKFLOW_START is emitted even if the stream errors immediately."""

        async def _immediate_error() -> AsyncGenerator[dict[str, Any], None]:
            raise ValueError("immediate failure")
            yield  # noqa: RET504 — makes this a generator

        events: list[BeddelEvent] = []
        with pytest.raises(ValueError, match="immediate failure"):
            async for event in map_adk_events(_immediate_error()):
                events.append(event)

        # WORKFLOW_START was yielded before the iteration started
        assert len(events) == 1
        assert events[0].event_type == EventType.WORKFLOW_START


# ---------------------------------------------------------------------------
# Synthetic bookend events
# ---------------------------------------------------------------------------


class TestSyntheticBookends:
    """WORKFLOW_START and WORKFLOW_END bookend the stream."""

    async def test_first_event_is_workflow_start(self) -> None:
        """The first yielded event is always WORKFLOW_START."""
        adk_events = [_make_text_event("hello")]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        assert results[0].event_type == EventType.WORKFLOW_START

    async def test_last_event_is_workflow_end(self) -> None:
        """The last yielded event is always WORKFLOW_END."""
        adk_events = [_make_text_event("hello")]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        assert results[-1].event_type == EventType.WORKFLOW_END

    async def test_bookends_have_no_step_id(self) -> None:
        """Synthetic bookend events have step_id=None."""
        results = await _collect(map_adk_events(_adk_stream([])))

        assert results[0].step_id is None
        assert results[1].step_id is None

    async def test_bookends_have_empty_data(self) -> None:
        """Synthetic bookend events have empty data dicts."""
        results = await _collect(map_adk_events(_adk_stream([])))

        assert results[0].data == {}
        assert results[1].data == {}


# ---------------------------------------------------------------------------
# Full pipeline sequence
# ---------------------------------------------------------------------------


class TestFullPipelineSequence:
    """End-to-end ADK event sequence maps to correct BeddelEvent order."""

    async def test_full_tool_call_with_text_response(self) -> None:
        """A realistic ADK sequence: tool call → tool response → text summary.

        Expected BeddelEvent sequence:
        1. WORKFLOW_START (synthetic)
        2. STEP_START (functionCall)
        3. STEP_END (functionResponse)
        4. TEXT_CHUNK (text summary)
        5. WORKFLOW_END (synthetic)
        """
        adk_events = [
            _make_function_call_event("research_pipeline", {"topic": "AI"}),
            _make_function_response_event(
                "research_pipeline",
                {"result": "AI research complete"},
            ),
            _make_text_event("Here is your AI research summary."),
        ]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        expected_types = [
            EventType.WORKFLOW_START,
            EventType.STEP_START,
            EventType.STEP_END,
            EventType.TEXT_CHUNK,
            EventType.WORKFLOW_END,
        ]
        actual_types = [e.event_type for e in results]
        assert actual_types == expected_types

    async def test_multiple_parts_in_single_event(self) -> None:
        """An ADK event with multiple parts yields multiple BeddelEvents."""
        adk_events = [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"functionCall": {"name": "tool_a", "args": {}}},
                        {"text": "Calling tool_a..."},
                    ],
                },
            },
        ]
        results = await _collect(map_adk_events(_adk_stream(adk_events)))

        core_events = [
            e
            for e in results
            if e.event_type not in (EventType.WORKFLOW_START, EventType.WORKFLOW_END)
        ]
        assert len(core_events) == 2
        assert core_events[0].event_type == EventType.STEP_START
        assert core_events[0].step_id == "tool_a"
        assert core_events[1].event_type == EventType.TEXT_CHUNK
        assert core_events[1].data["text"] == "Calling tool_a..."
