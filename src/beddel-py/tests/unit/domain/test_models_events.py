"""Unit tests for BeddelEventType and BeddelEvent models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from beddel.domain.models import BeddelEvent, BeddelEventType

# ---------------------------------------------------------------------------
# 6.1 BeddelEventType enum
# ---------------------------------------------------------------------------


class TestBeddelEventType:
    """BeddelEventType is a StrEnum with all 7 expected values."""

    def test_is_str_enum(self) -> None:
        """BeddelEventType is a StrEnum subclass."""
        assert issubclass(BeddelEventType, StrEnum)

    def test_has_seven_members(self) -> None:
        """BeddelEventType has exactly 7 members."""
        assert len(BeddelEventType) == 7

    def test_expected_values(self) -> None:
        """BeddelEventType contains all expected event type values."""
        expected = {
            "workflow_start",
            "workflow_end",
            "step_start",
            "step_end",
            "text_chunk",
            "step_result",
            "error",
        }
        actual = {member.value for member in BeddelEventType}
        assert actual == expected

    def test_member_names(self) -> None:
        """BeddelEventType members have SCREAMING_SNAKE_CASE names."""
        expected_names = {
            "WORKFLOW_START",
            "WORKFLOW_END",
            "STEP_START",
            "STEP_END",
            "TEXT_CHUNK",
            "STEP_RESULT",
            "ERROR",
        }
        actual_names = {member.name for member in BeddelEventType}
        assert actual_names == expected_names

    def test_str_value(self) -> None:
        """BeddelEventType members are usable as strings."""
        assert str(BeddelEventType.WORKFLOW_START) == "workflow_start"
        assert f"{BeddelEventType.ERROR}" == "error"


# ---------------------------------------------------------------------------
# 6.2 BeddelEvent model
# ---------------------------------------------------------------------------


class TestBeddelEvent:
    """BeddelEvent Pydantic model construction and serialization."""

    def test_construction_with_all_fields(self) -> None:
        """BeddelEvent can be constructed with all fields explicitly."""
        ts = datetime(2026, 2, 11, 12, 0, 0, tzinfo=UTC)
        event = BeddelEvent(
            type=BeddelEventType.WORKFLOW_START,
            workflow_id="wf-123",
            step_id="step-1",
            data={"key": "value"},
            timestamp=ts,
        )
        assert event.type == BeddelEventType.WORKFLOW_START
        assert event.workflow_id == "wf-123"
        assert event.step_id == "step-1"
        assert event.data == {"key": "value"}
        assert event.timestamp == ts

    def test_default_step_id_is_none(self) -> None:
        """BeddelEvent.step_id defaults to None."""
        event = BeddelEvent(
            type=BeddelEventType.WORKFLOW_END,
            workflow_id="wf-456",
        )
        assert event.step_id is None

    def test_default_data_is_none(self) -> None:
        """BeddelEvent.data defaults to None."""
        event = BeddelEvent(
            type=BeddelEventType.STEP_END,
            workflow_id="wf-789",
        )
        assert event.data is None

    def test_default_timestamp_is_set(self) -> None:
        """BeddelEvent.timestamp defaults to a UTC datetime."""
        before = datetime.now(UTC)
        event = BeddelEvent(
            type=BeddelEventType.TEXT_CHUNK,
            workflow_id="wf-ts",
        )
        after = datetime.now(UTC)
        assert before <= event.timestamp <= after

    def test_model_dump_json_mode(self) -> None:
        """model_dump(mode='json') serializes timestamp as ISO string and enum as string value."""
        ts = datetime(2026, 2, 11, 12, 0, 0, tzinfo=UTC)
        event = BeddelEvent(
            type=BeddelEventType.STEP_RESULT,
            workflow_id="wf-dump",
            step_id="s1",
            data={"output": 42},
            timestamp=ts,
        )
        dumped = event.model_dump(mode="json")

        assert dumped["type"] == "step_result"
        assert dumped["workflow_id"] == "wf-dump"
        assert dumped["step_id"] == "s1"
        assert dumped["data"] == {"output": 42}
        # Timestamp should be an ISO format string
        assert isinstance(dumped["timestamp"], str)
        assert "2026-02-11" in dumped["timestamp"]

    def test_model_dump_without_optional_fields(self) -> None:
        """model_dump(mode='json') includes None defaults."""
        event = BeddelEvent(
            type=BeddelEventType.ERROR,
            workflow_id="wf-err",
        )
        dumped = event.model_dump(mode="json")
        assert dumped["step_id"] is None
        assert dumped["data"] is None
