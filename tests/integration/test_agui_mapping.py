"""Unit tests for AG-UI event mapping (Story BC3.1, Task 5)."""

from __future__ import annotations

import pytest
from ag_ui.core import (
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageContentEvent,
)
from ag_ui.core import (
    EventType as AGUIEventType,
)
from beddel_ag_ui.mapping import map_event

from beddel.domain.models import BeddelEvent, EventType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KWARGS = {"thread_id": "t-1", "run_id": "r-1", "message_id": "m-1"}


def _make_event(
    event_type: EventType = EventType.WORKFLOW_START,
    step_id: str | None = None,
    data: dict | None = None,
) -> BeddelEvent:
    """Create a BeddelEvent with sensible defaults for mapping tests."""
    return BeddelEvent(
        event_type=event_type,
        step_id=step_id,
        data=data or {},
        timestamp=1000.0,
    )


# ---------------------------------------------------------------------------
# workflow_start → RunStartedEvent
# ---------------------------------------------------------------------------


class TestWorkflowStartMapping:
    """workflow_start events map to RunStartedEvent with correct identifiers."""

    def test_returns_run_started_event(self) -> None:
        """workflow_start produces a RunStartedEvent instance."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        result = map_event(event, **_KWARGS)

        assert isinstance(result, RunStartedEvent)

    def test_thread_id_matches_kwarg(self) -> None:
        """RunStartedEvent.thread_id matches the provided thread_id."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        result = map_event(event, **_KWARGS)

        assert result.thread_id == "t-1"

    def test_run_id_matches_kwarg(self) -> None:
        """RunStartedEvent.run_id matches the provided run_id."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        result = map_event(event, **_KWARGS)

        assert result.run_id == "r-1"

    def test_agui_event_type_is_run_started(self) -> None:
        """RunStartedEvent.type is RUN_STARTED."""
        event = _make_event(event_type=EventType.WORKFLOW_START)
        result = map_event(event, **_KWARGS)

        assert result.type == AGUIEventType.RUN_STARTED


# ---------------------------------------------------------------------------
# step_start → StepStartedEvent
# ---------------------------------------------------------------------------


class TestStepStartMapping:
    """step_start events map to StepStartedEvent with step_name from step_id."""

    def test_returns_step_started_event(self) -> None:
        """step_start produces a StepStartedEvent instance."""
        event = _make_event(event_type=EventType.STEP_START, step_id="summarize")
        result = map_event(event, **_KWARGS)

        assert isinstance(result, StepStartedEvent)

    def test_step_name_matches_step_id(self) -> None:
        """StepStartedEvent.step_name equals the source event's step_id."""
        event = _make_event(event_type=EventType.STEP_START, step_id="summarize")
        result = map_event(event, **_KWARGS)

        assert result.step_name == "summarize"

    def test_missing_step_id_defaults_to_unknown(self) -> None:
        """When step_id is None, step_name falls back to 'unknown'."""
        event = _make_event(event_type=EventType.STEP_START, step_id=None)
        result = map_event(event, **_KWARGS)

        assert result.step_name == "unknown"

    def test_agui_event_type_is_step_started(self) -> None:
        """StepStartedEvent.type is STEP_STARTED."""
        event = _make_event(event_type=EventType.STEP_START, step_id="s1")
        result = map_event(event, **_KWARGS)

        assert result.type == AGUIEventType.STEP_STARTED


# ---------------------------------------------------------------------------
# step_end → StepFinishedEvent
# ---------------------------------------------------------------------------


class TestStepEndMapping:
    """step_end events map to StepFinishedEvent with step_name from step_id."""

    def test_returns_step_finished_event(self) -> None:
        """step_end produces a StepFinishedEvent instance."""
        event = _make_event(event_type=EventType.STEP_END, step_id="summarize")
        result = map_event(event, **_KWARGS)

        assert isinstance(result, StepFinishedEvent)

    def test_step_name_matches_step_id(self) -> None:
        """StepFinishedEvent.step_name equals the source event's step_id."""
        event = _make_event(event_type=EventType.STEP_END, step_id="summarize")
        result = map_event(event, **_KWARGS)

        assert result.step_name == "summarize"

    def test_missing_step_id_defaults_to_unknown(self) -> None:
        """When step_id is None, step_name falls back to 'unknown'."""
        event = _make_event(event_type=EventType.STEP_END, step_id=None)
        result = map_event(event, **_KWARGS)

        assert result.step_name == "unknown"

    def test_agui_event_type_is_step_finished(self) -> None:
        """StepFinishedEvent.type is STEP_FINISHED."""
        event = _make_event(event_type=EventType.STEP_END, step_id="s1")
        result = map_event(event, **_KWARGS)

        assert result.type == AGUIEventType.STEP_FINISHED


# ---------------------------------------------------------------------------
# text_chunk → TextMessageContentEvent
# ---------------------------------------------------------------------------


class TestTextChunkMapping:
    """text_chunk events map to TextMessageContentEvent with delta from data."""

    def test_returns_text_message_content_event(self) -> None:
        """text_chunk with non-empty text produces a TextMessageContentEvent."""
        event = _make_event(
            event_type=EventType.TEXT_CHUNK,
            data={"text": "Hello"},
        )
        result = map_event(event, **_KWARGS)

        assert isinstance(result, TextMessageContentEvent)

    def test_delta_matches_data_text(self) -> None:
        """TextMessageContentEvent.delta equals data['text']."""
        event = _make_event(
            event_type=EventType.TEXT_CHUNK,
            data={"text": "Hello world"},
        )
        result = map_event(event, **_KWARGS)

        assert result.delta == "Hello world"

    def test_message_id_matches_kwarg(self) -> None:
        """TextMessageContentEvent.message_id matches the provided message_id."""
        event = _make_event(
            event_type=EventType.TEXT_CHUNK,
            data={"text": "chunk"},
        )
        result = map_event(event, **_KWARGS)

        assert result.message_id == "m-1"

    def test_agui_event_type_is_text_message_content(self) -> None:
        """TextMessageContentEvent.type is TEXT_MESSAGE_CONTENT."""
        event = _make_event(
            event_type=EventType.TEXT_CHUNK,
            data={"text": "chunk"},
        )
        result = map_event(event, **_KWARGS)

        assert result.type == AGUIEventType.TEXT_MESSAGE_CONTENT

    def test_empty_text_returns_none(self) -> None:
        """text_chunk with empty string text returns None (AG-UI requires non-empty delta)."""
        event = _make_event(
            event_type=EventType.TEXT_CHUNK,
            data={"text": ""},
        )
        result = map_event(event, **_KWARGS)

        assert result is None

    def test_missing_text_key_returns_none(self) -> None:
        """text_chunk with no 'text' key in data returns None."""
        event = _make_event(
            event_type=EventType.TEXT_CHUNK,
            data={},
        )
        result = map_event(event, **_KWARGS)

        assert result is None


# ---------------------------------------------------------------------------
# workflow_end → RunFinishedEvent
# ---------------------------------------------------------------------------


class TestWorkflowEndMapping:
    """workflow_end events map to RunFinishedEvent with correct identifiers."""

    def test_returns_run_finished_event(self) -> None:
        """workflow_end produces a RunFinishedEvent instance."""
        event = _make_event(event_type=EventType.WORKFLOW_END)
        result = map_event(event, **_KWARGS)

        assert isinstance(result, RunFinishedEvent)

    def test_thread_id_matches_kwarg(self) -> None:
        """RunFinishedEvent.thread_id matches the provided thread_id."""
        event = _make_event(event_type=EventType.WORKFLOW_END)
        result = map_event(event, **_KWARGS)

        assert result.thread_id == "t-1"

    def test_run_id_matches_kwarg(self) -> None:
        """RunFinishedEvent.run_id matches the provided run_id."""
        event = _make_event(event_type=EventType.WORKFLOW_END)
        result = map_event(event, **_KWARGS)

        assert result.run_id == "r-1"

    def test_agui_event_type_is_run_finished(self) -> None:
        """RunFinishedEvent.type is RUN_FINISHED."""
        event = _make_event(event_type=EventType.WORKFLOW_END)
        result = map_event(event, **_KWARGS)

        assert result.type == AGUIEventType.RUN_FINISHED


# ---------------------------------------------------------------------------
# error → RunErrorEvent
# ---------------------------------------------------------------------------


class TestErrorMapping:
    """error events map to RunErrorEvent with message and code from data."""

    def test_returns_run_error_event(self) -> None:
        """error produces a RunErrorEvent instance."""
        event = _make_event(
            event_type=EventType.ERROR,
            data={"message": "something broke", "code": "ERR-42"},
        )
        result = map_event(event, **_KWARGS)

        assert isinstance(result, RunErrorEvent)

    def test_message_from_data(self) -> None:
        """RunErrorEvent.message equals data['message']."""
        event = _make_event(
            event_type=EventType.ERROR,
            data={"message": "step failed", "code": "ERR-01"},
        )
        result = map_event(event, **_KWARGS)

        assert result.message == "step failed"

    def test_code_from_data(self) -> None:
        """RunErrorEvent.code equals data['code']."""
        event = _make_event(
            event_type=EventType.ERROR,
            data={"message": "step failed", "code": "ERR-01"},
        )
        result = map_event(event, **_KWARGS)

        assert result.code == "ERR-01"

    def test_missing_message_defaults_to_unknown_error(self) -> None:
        """When data has no 'message' key, defaults to 'Unknown error'."""
        event = _make_event(
            event_type=EventType.ERROR,
            data={"code": "ERR-99"},
        )
        result = map_event(event, **_KWARGS)

        assert result.message == "Unknown error"

    def test_missing_code_defaults_to_none(self) -> None:
        """When data has no 'code' key, code is None."""
        event = _make_event(
            event_type=EventType.ERROR,
            data={"message": "oops"},
        )
        result = map_event(event, **_KWARGS)

        assert result.code is None

    def test_agui_event_type_is_run_error(self) -> None:
        """RunErrorEvent.type is RUN_ERROR."""
        event = _make_event(
            event_type=EventType.ERROR,
            data={"message": "err", "code": "E1"},
        )
        result = map_event(event, **_KWARGS)

        assert result.type == AGUIEventType.RUN_ERROR


# ---------------------------------------------------------------------------
# A2UI_SURFACE → CustomEvent (Story BC9.2, Task 2)
# ---------------------------------------------------------------------------


class TestA2UISurfaceMapping:
    """Tests for A2UI_SURFACE → CustomEvent mapping."""

    def test_returns_custom_event(self) -> None:
        """A2UI_SURFACE maps to a CustomEvent."""
        event = _make_event(EventType.A2UI_SURFACE, data={"surfaceUpdate": {"id": "s1"}})
        result = map_event(event, **_KWARGS)
        assert isinstance(result, CustomEvent)

    def test_custom_event_name_is_a2ui(self) -> None:
        """CustomEvent.name is 'a2ui'."""
        event = _make_event(EventType.A2UI_SURFACE, data={"surfaceUpdate": {"id": "s1"}})
        result = map_event(event, **_KWARGS)
        assert result is not None
        assert result.name == "a2ui"

    def test_custom_event_type_is_custom(self) -> None:
        """CustomEvent.type is AGUIEventType.CUSTOM."""
        event = _make_event(EventType.A2UI_SURFACE, data={"surfaceUpdate": {"id": "s1"}})
        result = map_event(event, **_KWARGS)
        assert result is not None
        assert result.type == AGUIEventType.CUSTOM

    def test_value_preserves_complex_data(self) -> None:
        """Complex nested A2UI data is preserved in CustomEvent.value."""
        complex_data = {
            "surfaceUpdate": {
                "id": "form-1",
                "components": [
                    {"type": "TextInput", "id": "name", "label": "Name"},
                    {"type": "Button", "id": "submit", "action": {"name": "submit"}},
                ],
            },
        }
        event = _make_event(EventType.A2UI_SURFACE, data=complex_data)
        result = map_event(event, **_KWARGS)
        assert result is not None
        assert result.value == complex_data

    def test_empty_data_returns_custom_event(self) -> None:
        """A2UI_SURFACE with empty data returns CustomEvent with empty dict."""
        event = _make_event(EventType.A2UI_SURFACE, data={})
        result = map_event(event, **_KWARGS)
        assert isinstance(result, CustomEvent)
        assert result.value == {}


# ---------------------------------------------------------------------------
# Unmapped event types → None
# ---------------------------------------------------------------------------


class TestUnmappedEventTypes:
    """Event types without AG-UI equivalents return None."""

    @pytest.mark.parametrize(
        "event_type",
        [
            EventType.LLM_START,
            EventType.LLM_END,
            EventType.RETRY,
            EventType.REFLECTION_START,
            EventType.REFLECTION_END,
            EventType.PARALLEL_START,
            EventType.PARALLEL_END,
            EventType.CIRCUIT_OPEN,
            EventType.CIRCUIT_CLOSE,
            EventType.GOAL_ATTEMPT,
            EventType.CHECKPOINT,
        ],
        ids=lambda et: et.value,
    )
    def test_unmapped_event_returns_none(self, event_type: EventType) -> None:
        """Unmapped EventType values produce None so callers can skip them."""
        event = _make_event(event_type=event_type)
        result = map_event(event, **_KWARGS)

        assert result is None
