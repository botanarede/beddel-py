"""Integration tests for episodic memory provider (Story 6.4, Task 5).

Tests the full pipeline: DefaultDependencies with InMemoryMemoryProvider →
set/get/search round-trip, episode lifecycle, CompositeMemoryProvider routing
isolation, and backward compatibility when memory_provider is None.

AC #10: get/set round-trip, search with scoring, episode creation/listing,
        composite routing, error handling for missing provider.
AC #11: All 4 validation gates pass.
"""

from __future__ import annotations

import asyncio
import subprocess
import time

import pytest

from beddel.adapters.memory_provider import (
    CompositeMemoryProvider,
    InMemoryMemoryProvider,
)
from beddel.domain.models import (
    DefaultDependencies,
    Episode,
    ExecutionContext,
    MemoryEntry,
)

# ---------------------------------------------------------------------------
# 5.1 Full pipeline: create context → set → get → search → verify round-trip
# ---------------------------------------------------------------------------


class TestFullPipelineMemoryRoundTrip:
    """Full pipeline: ExecutionContext with InMemoryMemoryProvider."""

    @pytest.mark.asyncio
    async def test_set_get_round_trip_via_deps(self) -> None:
        """Create deps with InMemoryMemoryProvider, set values, get them back."""
        provider = InMemoryMemoryProvider()
        deps = DefaultDependencies(memory_provider=provider)
        ctx = ExecutionContext(workflow_id="wf-test", deps=deps)

        assert ctx.deps.memory_provider is provider

        await provider.set("user_name", "Alice")
        await provider.set("session_count", 42)
        await provider.set("preferences", {"theme": "dark", "lang": "en"})

        assert await provider.get("user_name") == "Alice"
        assert await provider.get("session_count") == 42
        assert await provider.get("preferences") == {"theme": "dark", "lang": "en"}

    @pytest.mark.asyncio
    async def test_search_after_set(self) -> None:
        """Set multiple values, search returns scored results."""
        provider = InMemoryMemoryProvider()
        deps = DefaultDependencies(memory_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-search", deps=deps)

        await provider.set("user_name", "Alice")
        await provider.set("user_email", "alice@example.com")
        await provider.set("order_id", "ORD-12345")

        results = await provider.search("user")

        assert len(results) == 2
        assert all(isinstance(r, MemoryEntry) for r in results)
        keys = {r.key for r in results}
        assert keys == {"user_name", "user_email"}
        # Key matches score 1.0
        for r in results:
            assert r.score == 1.0

    @pytest.mark.asyncio
    async def test_search_value_match(self) -> None:
        """Search finds entries where query matches the value."""
        provider = InMemoryMemoryProvider()
        deps = DefaultDependencies(memory_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-val-search", deps=deps)

        await provider.set("greeting", "hello world")
        await provider.set("farewell", "goodbye")

        results = await provider.search("hello")

        assert len(results) == 1
        assert results[0].key == "greeting"
        assert results[0].value == "hello world"
        assert results[0].score == 0.8

    @pytest.mark.asyncio
    async def test_overwrite_and_get(self) -> None:
        """Overwriting a key returns the latest value."""
        provider = InMemoryMemoryProvider()
        deps = DefaultDependencies(memory_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-overwrite", deps=deps)

        await provider.set("counter", 1)
        await provider.set("counter", 2)

        assert await provider.get("counter") == 2

    @pytest.mark.asyncio
    async def test_get_missing_key(self) -> None:
        """Getting a non-existent key returns None."""
        provider = InMemoryMemoryProvider()
        deps = DefaultDependencies(memory_provider=provider)
        _ctx = ExecutionContext(workflow_id="wf-missing", deps=deps)

        assert await provider.get("nonexistent") is None


# ---------------------------------------------------------------------------
# 5.2 Episode lifecycle: create → list → verify metadata
# ---------------------------------------------------------------------------


class TestEpisodeLifecycle:
    """Episode creation, listing, and metadata verification."""

    @pytest.mark.asyncio
    async def test_create_and_list_episode(self) -> None:
        """Create an episode with all fields, list it, verify all fields match."""
        provider = InMemoryMemoryProvider()
        now = time.time()

        ep = Episode(
            workflow_id="wf-episode-test",
            episode_id="ep-001",
            inputs={"prompt": "summarize this", "max_tokens": 100},
            outputs={"text": "Summary of the document.", "tokens_used": 42},
            duration_ms=1234.5,
            created_at=now,
            metadata={"model": "gpt-4o", "run_id": "run-abc-123"},
        )
        provider.add_episode(ep)

        episodes = await provider.list_episodes("wf-episode-test")

        assert len(episodes) == 1
        result = episodes[0]
        assert result.workflow_id == "wf-episode-test"
        assert result.episode_id == "ep-001"
        assert result.inputs == {"prompt": "summarize this", "max_tokens": 100}
        assert result.outputs == {"text": "Summary of the document.", "tokens_used": 42}
        assert result.duration_ms == 1234.5
        assert result.created_at == now
        assert result.metadata == {"model": "gpt-4o", "run_id": "run-abc-123"}

    @pytest.mark.asyncio
    async def test_multiple_episodes_same_workflow(self) -> None:
        """Multiple episodes for the same workflow are all returned."""
        provider = InMemoryMemoryProvider()

        for i in range(3):
            ep = Episode(
                workflow_id="wf-multi",
                episode_id=f"ep-{i}",
                inputs={"iteration": i},
                outputs={"result": f"output-{i}"},
                duration_ms=float(i * 100),
                created_at=1000.0 + i,
            )
            provider.add_episode(ep)

        episodes = await provider.list_episodes("wf-multi")

        assert len(episodes) == 3
        assert [ep.episode_id for ep in episodes] == ["ep-0", "ep-1", "ep-2"]

    @pytest.mark.asyncio
    async def test_episodes_filtered_by_workflow_id(self) -> None:
        """Episodes for different workflows are isolated."""
        provider = InMemoryMemoryProvider()

        provider.add_episode(
            Episode(
                workflow_id="wf-a",
                episode_id="ep-a",
                inputs={},
                outputs={},
                duration_ms=10.0,
                created_at=1000.0,
            )
        )
        provider.add_episode(
            Episode(
                workflow_id="wf-b",
                episode_id="ep-b",
                inputs={},
                outputs={},
                duration_ms=20.0,
                created_at=2000.0,
            )
        )

        assert len(await provider.list_episodes("wf-a")) == 1
        assert len(await provider.list_episodes("wf-b")) == 1
        assert (await provider.list_episodes("wf-a"))[0].episode_id == "ep-a"
        assert (await provider.list_episodes("wf-b"))[0].episode_id == "ep-b"

    @pytest.mark.asyncio
    async def test_list_episodes_empty_workflow(self) -> None:
        """Listing episodes for a non-existent workflow returns empty list."""
        provider = InMemoryMemoryProvider()

        assert await provider.list_episodes("wf-nonexistent") == []


# ---------------------------------------------------------------------------
# 5.3 CompositeMemoryProvider routing isolation
# ---------------------------------------------------------------------------


class TestCompositeRoutingIsolation:
    """CompositeMemoryProvider with two InMemoryMemoryProvider backends."""

    @pytest.mark.asyncio
    async def test_set_routes_to_structured_not_semantic(self) -> None:
        """set() via composite writes to structured backend only."""
        structured = InMemoryMemoryProvider()
        semantic = InMemoryMemoryProvider()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        await composite.set("key1", "value1")
        # Allow background task to complete
        await asyncio.sleep(0)

        assert await structured.get("key1") == "value1"
        assert await semantic.get("key1") is None

    @pytest.mark.asyncio
    async def test_get_routes_to_structured(self) -> None:
        """get() reads from structured backend."""
        structured = InMemoryMemoryProvider()
        semantic = InMemoryMemoryProvider()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        await structured.set("key1", "from-structured")
        await semantic.set("key1", "from-semantic")

        result = await composite.get("key1")
        assert result == "from-structured"

    @pytest.mark.asyncio
    async def test_search_routes_to_semantic(self) -> None:
        """search() queries the semantic backend, not structured."""
        structured = InMemoryMemoryProvider()
        semantic = InMemoryMemoryProvider()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        await structured.set("structured_key", "structured_value")
        await semantic.set("semantic_key", "semantic_value")

        results = await composite.search("semantic")

        assert len(results) == 1
        assert results[0].key == "semantic_key"

        # Structured key should NOT appear in search results
        structured_results = await composite.search("structured")
        assert len(structured_results) == 0

    @pytest.mark.asyncio
    async def test_list_episodes_routes_to_structured(self) -> None:
        """list_episodes() reads from structured backend."""
        structured = InMemoryMemoryProvider()
        semantic = InMemoryMemoryProvider()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        ep = Episode(
            workflow_id="wf-composite",
            episode_id="ep-1",
            inputs={"q": "test"},
            outputs={"a": "result"},
            duration_ms=50.0,
            created_at=1000.0,
        )
        structured.add_episode(ep)

        episodes = await composite.list_episodes("wf-composite")

        assert len(episodes) == 1
        assert episodes[0].episode_id == "ep-1"

    @pytest.mark.asyncio
    async def test_composite_full_round_trip(self) -> None:
        """Full round-trip: set via composite → get via composite → search via composite."""
        structured = InMemoryMemoryProvider()
        semantic = InMemoryMemoryProvider()
        composite = CompositeMemoryProvider(structured=structured, semantic=semantic)

        # Set via composite (goes to structured)
        await composite.set("agent_name", "beddel-agent")
        await asyncio.sleep(0)

        # Get via composite (reads from structured)
        assert await composite.get("agent_name") == "beddel-agent"

        # Seed semantic backend for search
        await semantic.set("agent_name", "beddel-agent")

        # Search via composite (reads from semantic)
        results = await composite.search("agent")
        assert len(results) == 1
        assert results[0].key == "agent_name"


# ---------------------------------------------------------------------------
# 5.4 Backward compatibility: memory_provider=None
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Verify no errors when memory_provider is not configured."""

    def test_default_deps_memory_provider_is_none(self) -> None:
        """DefaultDependencies() without memory_provider has None."""
        deps = DefaultDependencies()

        assert deps.memory_provider is None

    def test_execution_context_without_memory_provider(self) -> None:
        """ExecutionContext with default deps works without memory_provider."""
        ctx = ExecutionContext(workflow_id="wf-no-memory")

        assert ctx.deps.memory_provider is None

    def test_execution_context_with_other_deps_no_memory(self) -> None:
        """DefaultDependencies with other deps but no memory_provider is fine."""
        deps = DefaultDependencies(delegate_model="gpt-4o")

        assert deps.memory_provider is None
        assert deps.delegate_model == "gpt-4o"


# ---------------------------------------------------------------------------
# 5.6 Domain isolation: no adapter imports in domain core
# ---------------------------------------------------------------------------


class TestDomainIsolation:
    """Verify domain core never imports from adapters."""

    def test_no_adapter_imports_in_domain(self) -> None:
        """grep for adapter imports in domain/ returns zero matches."""
        result = subprocess.run(
            [
                "grep",
                "-r",
                "from beddel.adapters",
                "src/beddel-py/src/beddel/domain/",
            ],
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", f"Domain core imports from adapters:\n{result.stdout}"
