"""Memory provider adapters for episodic memory.

Provides :class:`InMemoryMemoryProvider` — a dict-based in-memory
implementation of :class:`~beddel.domain.ports.IMemoryProvider` for testing.
"""

from __future__ import annotations

from typing import Any

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
