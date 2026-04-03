"""Tests for InMemoryMemoryProvider adapter."""

from __future__ import annotations

import pytest

from beddel.adapters.memory_provider import InMemoryMemoryProvider
from beddel.domain.errors import MemoryError as MemoryError  # noqa: A004
from beddel.domain.models import Episode, MemoryEntry
from beddel.error_codes import (
    MEMORY_EPISODE_FAILED,
    MEMORY_GET_FAILED,
    MEMORY_SEARCH_FAILED,
    MEMORY_SET_FAILED,
)


class TestInMemoryMemoryProvider:
    """Unit tests for the InMemoryMemoryProvider adapter."""

    @pytest.mark.asyncio
    async def test_set_and_get_round_trip(self) -> None:
        """Set a value and get it back — verify content matches."""
        provider = InMemoryMemoryProvider()

        await provider.set("key1", {"data": [1, 2, 3]})
        result = await provider.get("key1")

        assert result == {"data": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self) -> None:
        """Get for unknown key returns None."""
        provider = InMemoryMemoryProvider()

        result = await provider.get("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_set_overwrites(self) -> None:
        """Setting the same key twice overwrites the previous value."""
        provider = InMemoryMemoryProvider()

        await provider.set("key1", "first")
        await provider.set("key1", "second")

        assert await provider.get("key1") == "second"

    @pytest.mark.asyncio
    async def test_search_with_results_key_match(self) -> None:
        """Search finds entries where query matches the key."""
        provider = InMemoryMemoryProvider()
        await provider.set("user_name", "Alice")
        await provider.set("user_email", "alice@example.com")
        await provider.set("order_id", "12345")

        results = await provider.search("user")

        assert len(results) == 2
        keys = {r.key for r in results}
        assert keys == {"user_name", "user_email"}
        # Key matches get score 1.0
        for r in results:
            assert r.score == 1.0

    @pytest.mark.asyncio
    async def test_search_with_results_value_match(self) -> None:
        """Search finds entries where query matches the value."""
        provider = InMemoryMemoryProvider()
        await provider.set("greeting", "hello world")
        await provider.set("farewell", "goodbye")

        results = await provider.search("hello")

        assert len(results) == 1
        assert results[0].key == "greeting"
        assert results[0].score == 0.8

    @pytest.mark.asyncio
    async def test_search_key_match_scores_higher_than_value(self) -> None:
        """Key matches (1.0) rank above value matches (0.8)."""
        provider = InMemoryMemoryProvider()
        await provider.set("hello_key", "unrelated")
        await provider.set("other", "hello value")

        results = await provider.search("hello")

        assert len(results) == 2
        assert results[0].key == "hello_key"
        assert results[0].score == 1.0
        assert results[1].key == "other"
        assert results[1].score == 0.8

    @pytest.mark.asyncio
    async def test_search_empty_results(self) -> None:
        """Search with no matches returns empty list."""
        provider = InMemoryMemoryProvider()
        await provider.set("key1", "value1")

        results = await provider.search("nonexistent")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_empty_store(self) -> None:
        """Search on empty store returns empty list."""
        provider = InMemoryMemoryProvider()

        results = await provider.search("anything")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_top_k(self) -> None:
        """Search returns at most top_k results."""
        provider = InMemoryMemoryProvider()
        for i in range(10):
            await provider.set(f"item_{i}", f"data_{i}")

        results = await provider.search("item", top_k=3)

        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self) -> None:
        """Search is case-insensitive."""
        provider = InMemoryMemoryProvider()
        await provider.set("UserName", "Alice")

        results = await provider.search("username")

        assert len(results) == 1
        assert results[0].key == "UserName"

    @pytest.mark.asyncio
    async def test_search_returns_memory_entry(self) -> None:
        """Search results are MemoryEntry instances."""
        provider = InMemoryMemoryProvider()
        await provider.set("key1", "value1")

        results = await provider.search("key1")

        assert len(results) == 1
        assert isinstance(results[0], MemoryEntry)
        assert results[0].key == "key1"
        assert results[0].value == "value1"

    @pytest.mark.asyncio
    async def test_list_episodes(self) -> None:
        """List episodes returns episodes for the given workflow_id."""
        provider = InMemoryMemoryProvider()
        ep1 = Episode(
            workflow_id="wf-1",
            episode_id="ep-1",
            inputs={"q": "hello"},
            outputs={"a": "world"},
            duration_ms=100.0,
            created_at=1000.0,
        )
        ep2 = Episode(
            workflow_id="wf-1",
            episode_id="ep-2",
            inputs={"q": "foo"},
            outputs={"a": "bar"},
            duration_ms=200.0,
            created_at=2000.0,
        )
        ep3 = Episode(
            workflow_id="wf-2",
            episode_id="ep-3",
            inputs={},
            outputs={},
            duration_ms=50.0,
            created_at=3000.0,
        )
        provider.add_episode(ep1)
        provider.add_episode(ep2)
        provider.add_episode(ep3)

        wf1_episodes = await provider.list_episodes("wf-1")
        wf2_episodes = await provider.list_episodes("wf-2")

        assert len(wf1_episodes) == 2
        assert wf1_episodes[0].episode_id == "ep-1"
        assert wf1_episodes[1].episode_id == "ep-2"
        assert len(wf2_episodes) == 1
        assert wf2_episodes[0].episode_id == "ep-3"

    @pytest.mark.asyncio
    async def test_list_episodes_empty(self) -> None:
        """List episodes for unknown workflow_id returns empty list."""
        provider = InMemoryMemoryProvider()

        result = await provider.list_episodes("nonexistent")

        assert result == []

    @pytest.mark.asyncio
    async def test_add_episode(self) -> None:
        """add_episode stores an episode retrievable via list_episodes."""
        provider = InMemoryMemoryProvider()
        ep = Episode(
            workflow_id="wf-1",
            episode_id="ep-1",
            inputs={"x": 1},
            outputs={"y": 2},
            duration_ms=42.0,
            created_at=9999.0,
            metadata={"tag": "test"},
        )

        provider.add_episode(ep)
        episodes = await provider.list_episodes("wf-1")

        assert len(episodes) == 1
        assert episodes[0] == ep
        assert episodes[0].metadata == {"tag": "test"}

    @pytest.mark.asyncio
    async def test_get_error_raises_memory_error(self) -> None:
        """Internal error during get raises MemoryError(MEMORY_GET_FAILED)."""
        provider = InMemoryMemoryProvider()

        class BadDict(dict):  # type: ignore[type-arg]
            def get(self, key: str, default: object = None) -> object:
                raise RuntimeError("boom")

        provider._store = BadDict()  # type: ignore[assignment]

        with pytest.raises(MemoryError) as exc_info:
            await provider.get("key1")
        assert exc_info.value.code == MEMORY_GET_FAILED

    @pytest.mark.asyncio
    async def test_set_error_raises_memory_error(self) -> None:
        """Internal error during set raises MemoryError(MEMORY_SET_FAILED)."""
        provider = InMemoryMemoryProvider()

        class BadDict(dict):  # type: ignore[type-arg]
            def __setitem__(self, key: str, value: object) -> None:
                raise RuntimeError("boom")

        provider._store = BadDict()  # type: ignore[assignment]

        with pytest.raises(MemoryError) as exc_info:
            await provider.set("key1", "val")
        assert exc_info.value.code == MEMORY_SET_FAILED

    @pytest.mark.asyncio
    async def test_search_error_raises_memory_error(self) -> None:
        """Internal error during search raises MemoryError(MEMORY_SEARCH_FAILED)."""
        provider = InMemoryMemoryProvider()

        class BadDict(dict):  # type: ignore[type-arg]
            def items(self) -> object:
                raise RuntimeError("boom")

        provider._store = BadDict()  # type: ignore[assignment]

        with pytest.raises(MemoryError) as exc_info:
            await provider.search("query")
        assert exc_info.value.code == MEMORY_SEARCH_FAILED

    @pytest.mark.asyncio
    async def test_list_episodes_error_raises_memory_error(self) -> None:
        """Internal error during list_episodes raises MemoryError(MEMORY_EPISODE_FAILED)."""
        provider = InMemoryMemoryProvider()

        class BadList(list):  # type: ignore[type-arg]
            def __iter__(self) -> object:
                raise RuntimeError("boom")

        provider._episodes = BadList()  # type: ignore[assignment]

        with pytest.raises(MemoryError) as exc_info:
            await provider.list_episodes("wf-1")
        assert exc_info.value.code == MEMORY_EPISODE_FAILED

    @pytest.mark.asyncio
    async def test_multiple_keys_isolated(self) -> None:
        """Values for different keys are independent."""
        provider = InMemoryMemoryProvider()

        await provider.set("a", 1)
        await provider.set("b", 2)

        assert await provider.get("a") == 1
        assert await provider.get("b") == 2
