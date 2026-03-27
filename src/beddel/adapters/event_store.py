"""In-memory event store adapter for durable execution checkpointing.

Implements :class:`~beddel.domain.ports.IEventStore` with thread-safe
in-memory storage.  Events are stored per ``workflow_id`` in insertion
order using a plain ``dict[str, list[dict[str, Any]]]``.

Uses ``asyncio.Lock`` for synchronization — safe for concurrent async
tasks sharing the same event store instance.
"""

from __future__ import annotations

import asyncio
from typing import Any


class InMemoryEventStore:
    """Thread-safe in-memory event store keyed by workflow ID.

    Satisfies the :class:`~beddel.domain.ports.IEventStore` protocol
    via structural subtyping.

    Events are stored in insertion order per ``workflow_id``.  Each stored
    event dict is augmented with a ``"step_id"`` key identifying the step
    that produced it.
    """

    def __init__(self) -> None:
        self._store: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def append(self, workflow_id: str, step_id: str, event: dict[str, Any]) -> None:
        """Append an event for a workflow step.

        Args:
            workflow_id: Identifier of the workflow execution.
            step_id: Identifier of the step that produced the event.
            event: Arbitrary event payload to store.
        """
        async with self._lock:
            if workflow_id not in self._store:
                self._store[workflow_id] = []
            self._store[workflow_id].append({**event, "step_id": step_id})

    async def load(self, workflow_id: str) -> list[dict[str, Any]]:
        """Load all events for a workflow in insertion order.

        Returns a shallow copy of the internal list so callers cannot
        mutate the store by modifying the returned list.

        Args:
            workflow_id: Identifier of the workflow execution.

        Returns:
            List of stored event dicts, in insertion order.
        """
        async with self._lock:
            return [dict(e) for e in self._store.get(workflow_id, [])]

    async def truncate(self, workflow_id: str) -> None:
        """Remove all events for a workflow.

        No-op if the workflow ID is not present.

        Args:
            workflow_id: Identifier of the workflow execution to clear.
        """
        async with self._lock:
            self._store.pop(workflow_id, None)
