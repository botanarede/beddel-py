"""Event store adapters for durable execution checkpointing.

Provides two :class:`~beddel.domain.ports.IEventStore` implementations:

- :class:`InMemoryEventStore` — thread-safe in-memory storage.
- :class:`SQLiteEventStore` — persistent SQLite-backed storage with
  ``asyncio.to_thread()`` for non-blocking I/O and exactly-once
  semantics via idempotency keys.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from beddel.domain.errors import DurableError
from beddel.error_codes import DURABLE_CORRUPT_DATA, DURABLE_READ_FAILED, DURABLE_WRITE_FAILED


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


class SQLiteEventStore:
    """Persistent SQLite-backed event store keyed by workflow ID.

    Satisfies the :class:`~beddel.domain.ports.IEventStore` protocol
    via structural subtyping.  Uses ``asyncio.to_thread()`` to wrap
    synchronous ``sqlite3`` calls for non-blocking async I/O.

    Each database operation opens a short-lived connection with WAL
    journal mode for improved concurrent read performance.

    Exactly-once semantics are enforced via a UNIQUE constraint on
    ``idempotency_key`` combined with ``INSERT OR IGNORE``.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived connection with WAL mode enabled."""
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        """Create the events table and index if they don't exist."""
        conn = self._connect()
        with conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "workflow_id TEXT NOT NULL, "
                "step_id TEXT NOT NULL, "
                "idempotency_key TEXT NOT NULL UNIQUE, "
                "event_data TEXT NOT NULL, "
                "created_at REAL NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_workflow_id ON events (workflow_id)"
            )
        conn.close()

    async def _ensure_initialized(self) -> None:
        """Initialize the database schema on first use."""
        if not self._initialized:
            await asyncio.to_thread(self._init_schema)
            self._initialized = True

    async def append(self, workflow_id: str, step_id: str, event: dict[str, Any]) -> None:
        """Append an event for a workflow step.

        Uses ``INSERT OR IGNORE`` with a UNIQUE ``idempotency_key`` to
        guarantee exactly-once semantics.

        Args:
            workflow_id: Identifier of the workflow execution.
            step_id: Identifier of the step that produced the event.
            event: Arbitrary event payload to store.
        """
        await self._ensure_initialized()
        idempotency_key = event.get("idempotency_key", f"{workflow_id}:{step_id}:0")
        event_data = json.dumps(event)
        created_at = time.time()

        def _write() -> None:
            try:
                conn = self._connect()
                with conn:
                    conn.execute(
                        "INSERT OR IGNORE INTO events "
                        "(workflow_id, step_id, idempotency_key, event_data, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (workflow_id, step_id, idempotency_key, event_data, created_at),
                    )
                conn.close()
            except sqlite3.Error as exc:
                raise DurableError(
                    DURABLE_WRITE_FAILED,
                    f"Failed to append event for workflow {workflow_id!r}: {exc}",
                ) from exc

        await asyncio.to_thread(_write)

    async def load(self, workflow_id: str) -> list[dict[str, Any]]:
        """Load all events for a workflow in insertion order.

        Each returned event dict is augmented with a ``"step_id"`` key
        identifying the step that produced it.

        Args:
            workflow_id: Identifier of the workflow execution.

        Returns:
            List of stored event dicts, in insertion order.
        """
        await self._ensure_initialized()

        def _read() -> list[dict[str, Any]]:
            try:
                conn = self._connect()
                with conn:
                    rows = conn.execute(
                        "SELECT event_data, step_id FROM events WHERE workflow_id = ? ORDER BY id",
                        (workflow_id,),
                    ).fetchall()
                conn.close()
            except sqlite3.Error as exc:
                raise DurableError(
                    DURABLE_READ_FAILED,
                    f"Failed to load events for workflow {workflow_id!r}: {exc}",
                ) from exc

            events: list[dict[str, Any]] = []
            for event_data, step_id in rows:
                try:
                    evt = json.loads(event_data)
                except json.JSONDecodeError as exc:
                    raise DurableError(
                        DURABLE_CORRUPT_DATA,
                        f"Corrupt event data for workflow {workflow_id!r}: {exc}",
                    ) from exc
                evt["step_id"] = step_id
                events.append(evt)
            return events

        return await asyncio.to_thread(_read)

    async def truncate(self, workflow_id: str) -> None:
        """Remove all events for a workflow.

        No-op if the workflow ID has no events.

        Args:
            workflow_id: Identifier of the workflow execution to clear.
        """
        await self._ensure_initialized()

        def _delete() -> None:
            try:
                conn = self._connect()
                with conn:
                    conn.execute(
                        "DELETE FROM events WHERE workflow_id = ?",
                        (workflow_id,),
                    )
                conn.close()
            except sqlite3.Error as exc:
                raise DurableError(
                    DURABLE_WRITE_FAILED,
                    f"Failed to truncate events for workflow {workflow_id!r}: {exc}",
                ) from exc

        await asyncio.to_thread(_delete)
