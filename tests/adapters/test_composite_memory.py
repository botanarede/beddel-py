"""Tests for CompositeMemoryProvider adapter."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from beddel.adapters.memory_provider import CompositeMemoryProvider
from beddel.domain.models import Episode, MemoryEntry


def _make_structured() -> AsyncMock:
    """Create a mock structured backend with default return values."""
    mock = AsyncMock()
    mock.get.return_value = "structured-value"
    mock.set.return_value = None
    mock.list_episodes.return_value = []
    mock.search.return_value = []
    return mock


def _make_semantic() -> AsyncMock:
    """Create a mock semantic backend with default return values."""
    mock = AsyncMock()
    mock.search.return_value = [
        MemoryEntry(key="sem-key", value="sem-val", score=0.95),
    ]
    mock.get.return_value = None
    mock.set.return_value = None
    mock.list_episodes.return_value = []
    return mock


class TestCompositeMemoryProviderRouting:
    """Verify that operations are routed to the correct backend."""

    @pytest.mark.asyncio
    async def test_get_routes_to_structured(self) -> None:
        """get() delegates to the structured backend."""
        structured = _make_structured()
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        result = await composite.get("my-key")

        assert result == "structured-value"
        structured.get.assert_awaited_once_with("my-key")
        semantic.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_search_routes_to_semantic(self) -> None:
        """search() delegates to the semantic backend."""
        structured = _make_structured()
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        results = await composite.search("hello", top_k=3)

        assert len(results) == 1
        assert results[0].key == "sem-key"
        semantic.search.assert_awaited_once_with("hello", 3)
        structured.search.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_list_episodes_routes_to_structured(self) -> None:
        """list_episodes() delegates to the structured backend."""
        ep = Episode(
            workflow_id="wf-1",
            episode_id="ep-1",
            inputs={},
            outputs={},
            duration_ms=10.0,
            created_at=1000.0,
        )
        structured = _make_structured()
        structured.list_episodes.return_value = [ep]
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        result = await composite.list_episodes("wf-1")

        assert result == [ep]
        structured.list_episodes.assert_awaited_once_with("wf-1")
        semantic.list_episodes.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_set_routes_to_structured(self) -> None:
        """set() schedules a write on the structured backend."""
        structured = _make_structured()
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        await composite.set("k", "v")
        # Allow the background task to complete
        await asyncio.sleep(0)

        structured.set.assert_awaited_once_with("k", "v")
        semantic.set.assert_not_awaited()


class TestCompositeMemoryProviderAsyncBuffering:
    """Verify that set() is non-blocking via asyncio.create_task."""

    @pytest.mark.asyncio
    async def test_set_returns_immediately(self) -> None:
        """set() returns before the structured backend write completes."""
        write_started = asyncio.Event()
        write_gate = asyncio.Event()

        async def slow_set(key: str, value: Any) -> None:
            write_started.set()
            await write_gate.wait()

        structured = _make_structured()
        structured.set = slow_set  # type: ignore[assignment]
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        # set() should return immediately — the write is still blocked
        await composite.set("k", "v")

        # The background task has started but not finished
        await asyncio.sleep(0)
        assert write_started.is_set()

        # Release the gate so the background task completes
        write_gate.set()
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_background_task_completes(self) -> None:
        """The background write eventually completes after set() returns."""
        structured = _make_structured()
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        await composite.set("k", "v")
        # Let the event loop run the background task
        await asyncio.sleep(0)
        # Allow the done callback to fire
        await asyncio.sleep(0)

        structured.set.assert_awaited_once_with("k", "v")
        # Task should be cleaned up from the set
        assert len(composite._background_tasks) == 0

    @pytest.mark.asyncio
    async def test_background_tasks_tracked(self) -> None:
        """Background tasks are stored to prevent GC, then cleaned up."""
        gate = asyncio.Event()

        async def blocked_set(key: str, value: Any) -> None:
            await gate.wait()

        structured = _make_structured()
        structured.set = blocked_set  # type: ignore[assignment]
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        await composite.set("k1", "v1")
        await composite.set("k2", "v2")
        await asyncio.sleep(0)

        # Tasks are tracked while pending
        assert len(composite._background_tasks) == 2

        # Release and let them finish
        gate.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(composite._background_tasks) == 0


class TestCompositeMemoryProviderErrorPropagation:
    """Verify that backend errors propagate to the caller."""

    @pytest.mark.asyncio
    async def test_get_error_propagates(self) -> None:
        """Error from structured.get() propagates through composite.get()."""
        structured = _make_structured()
        structured.get.side_effect = RuntimeError("structured boom")
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        with pytest.raises(RuntimeError, match="structured boom"):
            await composite.get("key")

    @pytest.mark.asyncio
    async def test_search_error_propagates(self) -> None:
        """Error from semantic.search() propagates through composite.search()."""
        structured = _make_structured()
        semantic = _make_semantic()
        semantic.search.side_effect = RuntimeError("semantic boom")
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        with pytest.raises(RuntimeError, match="semantic boom"):
            await composite.search("query")

    @pytest.mark.asyncio
    async def test_list_episodes_error_propagates(self) -> None:
        """Error from structured.list_episodes() propagates."""
        structured = _make_structured()
        structured.list_episodes.side_effect = RuntimeError("episode boom")
        semantic = _make_semantic()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        with pytest.raises(RuntimeError, match="episode boom"):
            await composite.list_episodes("wf-1")
