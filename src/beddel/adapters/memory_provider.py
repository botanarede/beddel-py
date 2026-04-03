"""Memory provider adapters for episodic memory.

Provides :class:`InMemoryMemoryProvider` — a dict-based in-memory
implementation of :class:`~beddel.domain.ports.IMemoryProvider` for testing,
and :class:`CompositeMemoryProvider` — a dual-backend adapter that routes
structured ops to one backend and semantic search to another.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from beddel.domain.ports import IMemoryProvider

from beddel.domain.errors import MemoryError as MemoryError  # noqa: A004
from beddel.domain.models import Episode, MemoryEntry
from beddel.error_codes import (
    MEMORY_EPISODE_FAILED,
    MEMORY_GET_FAILED,
    MEMORY_SEARCH_FAILED,
    MEMORY_SET_FAILED,
)


class InMemoryMemoryProvider:
    """Dict-based in-memory memory provider for testing.

    Satisfies the :class:`~beddel.domain.ports.IMemoryProvider` protocol
    via structural subtyping.

    Storage:
    - Key-value pairs in a ``dict[str, Any]``.
    - Episodes in a ``list[Episode]``.

    Search uses simple substring matching on stringified key+value
    with a normalized score (0.0–1.0).
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._episodes: list[Episode] = []

    async def get(self, key: str) -> Any | None:
        """Retrieve a value by key, or ``None`` if not present."""
        try:
            return self._store.get(key)
        except Exception as exc:
            raise MemoryError(
                MEMORY_GET_FAILED,
                f"Failed to get memory key {key!r}: {exc}",
            ) from exc

    async def set(self, key: str, value: Any) -> None:
        """Store a value by key."""
        try:
            self._store[key] = value
        except Exception as exc:
            raise MemoryError(
                MEMORY_SET_FAILED,
                f"Failed to set memory key {key!r}: {exc}",
            ) from exc

    async def search(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Search memory using substring matching on stringified key+value.

        Scoring:
        - query found in key → score = 1.0
        - query found in str(value) → score = 0.8
        - query found in both → score = 1.0

        Returns results sorted by score descending, capped at *top_k*.
        """
        try:
            results: list[MemoryEntry] = []
            query_lower = query.lower()

            for key, value in self._store.items():
                in_key = query_lower in key.lower()
                in_value = query_lower in str(value).lower()

                if in_key or in_value:
                    score = 1.0 if in_key else 0.8
                    results.append(MemoryEntry(key=key, value=value, score=min(score, 1.0)))

            results.sort(key=lambda e: e.score, reverse=True)
            return results[:top_k]
        except MemoryError:
            raise
        except Exception as exc:
            raise MemoryError(
                MEMORY_SEARCH_FAILED,
                f"Failed to search memory for {query!r}: {exc}",
            ) from exc

    async def list_episodes(self, workflow_id: str) -> list[Episode]:
        """Return episodes for a given workflow_id."""
        try:
            return [ep for ep in self._episodes if ep.workflow_id == workflow_id]
        except Exception as exc:
            raise MemoryError(
                MEMORY_EPISODE_FAILED,
                f"Failed to list episodes for {workflow_id!r}: {exc}",
            ) from exc

    def add_episode(self, episode: Episode) -> None:
        """Add an episode to the in-memory store (test helper)."""
        try:
            self._episodes.append(episode)
        except Exception as exc:
            raise MemoryError(
                MEMORY_EPISODE_FAILED,
                f"Failed to add episode: {exc}",
            ) from exc


class CompositeMemoryProvider:
    """Dual-backend memory provider that routes operations by type.

    Routes ``get``/``set``/``list_episodes`` to a *structured* backend and
    ``search`` to a *semantic* backend.  Both must satisfy the
    :class:`~beddel.domain.ports.IMemoryProvider` protocol.

    ``set()`` uses :func:`asyncio.create_task` for non-blocking writes —
    the caller's coroutine returns immediately while the structured backend
    persists in the background.

    [Source: docs/stories/epic-6/story-6.4.md — AC 5, AC 9]
    """

    def __init__(
        self,
        structured: IMemoryProvider,
        semantic: IMemoryProvider,
    ) -> None:
        self._structured = structured
        self._semantic = semantic
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def get(self, key: str) -> Any | None:
        """Retrieve a value from the structured backend."""
        return await self._structured.get(key)

    async def set(self, key: str, value: Any) -> None:
        """Schedule a write on the structured backend without blocking.

        The write is dispatched via :func:`asyncio.create_task` and the
        coroutine returns immediately.  A reference to the task is kept
        in ``_background_tasks`` to prevent garbage collection.
        """
        task: asyncio.Task[None] = asyncio.create_task(
            self._structured.set(key, value),
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def search(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        """Search the semantic backend."""
        return await self._semantic.search(query, top_k)

    async def list_episodes(self, workflow_id: str) -> list[Episode]:
        """List episodes from the structured backend."""
        return await self._structured.list_episodes(workflow_id)
