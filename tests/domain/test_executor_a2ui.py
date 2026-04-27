"""Tests for A2UI surface event emission in executor (Story BC9.3, Task 2)."""

from __future__ import annotations

import asyncio

from beddel.domain.models import BeddelEvent, EventType, ExecutionContext


class TestA2UISurfaceEmission:
    """Verify that _a2ui_surfaces metadata triggers A2UI_SURFACE events."""

    def test_a2ui_surfaces_metadata_structure(self) -> None:
        """_a2ui_surfaces is a list of dicts in context.metadata."""
        ctx = ExecutionContext(
            workflow_id="test",
            metadata={"_a2ui_surfaces": [{"surfaceUpdate": {"id": "s1"}}]},
        )
        surfaces = ctx.metadata.pop("_a2ui_surfaces", [])
        assert len(surfaces) == 1
        assert surfaces[0] == {"surfaceUpdate": {"id": "s1"}}
        # After pop, metadata is clean
        assert "_a2ui_surfaces" not in ctx.metadata

    def test_a2ui_surface_event_creation(self) -> None:
        """BeddelEvent with A2UI_SURFACE type can be created from surface data."""
        surface_data = {"surfaceUpdate": {"id": "form-1", "components": []}}
        event = BeddelEvent(
            event_type=EventType.A2UI_SURFACE,
            data=surface_data,
        )
        assert event.event_type == EventType.A2UI_SURFACE
        assert event.data == surface_data

    def test_a2ui_surface_queue_integration(self) -> None:
        """A2UI surface events can be put into an asyncio queue."""
        queue: asyncio.Queue[BeddelEvent] = asyncio.Queue()
        surfaces = [
            {"surfaceUpdate": {"id": "s1"}},
            {"dataModelUpdate": {"path": "form.name", "value": "Alice"}},
        ]
        for surface_data in surfaces:
            queue.put_nowait(
                BeddelEvent(
                    event_type=EventType.A2UI_SURFACE,
                    data=surface_data if isinstance(surface_data, dict) else {},
                )
            )
        assert queue.qsize() == 2
        event1 = queue.get_nowait()
        assert event1.event_type == EventType.A2UI_SURFACE
        assert event1.data == {"surfaceUpdate": {"id": "s1"}}

    def test_a2ui_surface_non_dict_guarded(self) -> None:
        """Non-dict surface data is replaced with empty dict for safety."""
        queue: asyncio.Queue[BeddelEvent] = asyncio.Queue()
        # Simulate a malformed entry (string instead of dict)
        surfaces: list[object] = ["not-a-dict", {"valid": True}]
        for surface_data in surfaces:
            queue.put_nowait(
                BeddelEvent(
                    event_type=EventType.A2UI_SURFACE,
                    data=surface_data if isinstance(surface_data, dict) else {},
                )
            )
        assert queue.qsize() == 2
        event1 = queue.get_nowait()
        assert event1.data == {}  # Guarded — non-dict becomes empty
        event2 = queue.get_nowait()
        assert event2.data == {"valid": True}

    def test_a2ui_surfaces_pop_clears_metadata(self) -> None:
        """Using pop() ensures _a2ui_surfaces is consumed and not re-emitted."""
        ctx = ExecutionContext(
            workflow_id="test",
            metadata={
                "_a2ui_surfaces": [{"surfaceUpdate": {"id": "s1"}}],
                "other_key": "preserved",
            },
        )
        # First pop consumes the list
        surfaces = ctx.metadata.pop("_a2ui_surfaces", [])
        assert len(surfaces) == 1
        # Second pop returns empty — no duplicate emission
        surfaces_again = ctx.metadata.pop("_a2ui_surfaces", [])
        assert surfaces_again == []
        # Other metadata is preserved
        assert ctx.metadata["other_key"] == "preserved"
