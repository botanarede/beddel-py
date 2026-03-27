"""Tests for InMemoryEventStore adapter."""

from __future__ import annotations

import pytest

from beddel.adapters.event_store import InMemoryEventStore


class TestInMemoryEventStore:
    """Unit tests for the InMemoryEventStore adapter."""

    @pytest.mark.asyncio
    async def test_append_and_load(self) -> None:
        """Append events and load them — verify order and content."""
        store = InMemoryEventStore()

        await store.append("wf-1", "step-a", {"result": "ok"})
        await store.append("wf-1", "step-b", {"result": "done"})

        events = await store.load("wf-1")

        assert len(events) == 2
        assert events[0]["result"] == "ok"
        assert events[0]["step_id"] == "step-a"
        assert events[1]["result"] == "done"
        assert events[1]["step_id"] == "step-b"

    @pytest.mark.asyncio
    async def test_load_empty(self) -> None:
        """Load for unknown workflow_id returns empty list."""
        store = InMemoryEventStore()

        events = await store.load("nonexistent")

        assert events == []

    @pytest.mark.asyncio
    async def test_truncate(self) -> None:
        """Append events, truncate, verify load returns empty."""
        store = InMemoryEventStore()

        await store.append("wf-1", "step-a", {"result": "ok"})
        await store.append("wf-1", "step-b", {"result": "done"})
        await store.truncate("wf-1")

        events = await store.load("wf-1")
        assert events == []

    @pytest.mark.asyncio
    async def test_truncate_nonexistent(self) -> None:
        """Truncate unknown workflow_id does not raise."""
        store = InMemoryEventStore()

        # Should not raise
        await store.truncate("nonexistent")

    @pytest.mark.asyncio
    async def test_append_preserves_step_id(self) -> None:
        """Verify step_id is included in stored event."""
        store = InMemoryEventStore()

        await store.append("wf-1", "my-step", {"data": 42})

        events = await store.load("wf-1")
        assert len(events) == 1
        assert events[0]["step_id"] == "my-step"
        assert events[0]["data"] == 42

    @pytest.mark.asyncio
    async def test_load_returns_copy(self) -> None:
        """Verify returned list is a copy — mutation doesn't affect store."""
        store = InMemoryEventStore()

        await store.append("wf-1", "step-a", {"result": "ok"})

        events = await store.load("wf-1")
        events.append({"step_id": "injected", "result": "bad"})
        events[0]["result"] = "mutated"

        # Reload — store should be unaffected by list mutation
        fresh = await store.load("wf-1")
        assert len(fresh) == 1
        assert fresh[0]["result"] == "ok"

    @pytest.mark.asyncio
    async def test_multiple_workflows_isolated(self) -> None:
        """Events for different workflow_ids are independent."""
        store = InMemoryEventStore()

        await store.append("wf-1", "step-a", {"result": "one"})
        await store.append("wf-2", "step-b", {"result": "two"})

        events_1 = await store.load("wf-1")
        events_2 = await store.load("wf-2")

        assert len(events_1) == 1
        assert events_1[0]["result"] == "one"
        assert len(events_2) == 1
        assert events_2[0]["result"] == "two"

        # Truncating one doesn't affect the other
        await store.truncate("wf-1")
        assert await store.load("wf-1") == []
        assert len(await store.load("wf-2")) == 1
