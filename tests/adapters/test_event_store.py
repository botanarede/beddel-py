"""Tests for event store adapters (InMemoryEventStore, SQLiteEventStore)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from beddel.adapters.event_store import InMemoryEventStore, SQLiteEventStore
from beddel.domain.errors import DurableError
from beddel.error_codes import DURABLE_CORRUPT_DATA, DURABLE_WRITE_FAILED


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


class TestSQLiteEventStore:
    """Unit tests for the SQLiteEventStore adapter."""

    @pytest.mark.asyncio
    async def test_sqlite_append_and_load(self, tmp_path: Path) -> None:
        """Append events and load them — verify order and content."""
        store = SQLiteEventStore(tmp_path / "test.db")

        await store.append("wf-1", "step-a", {"result": "ok"})
        await store.append("wf-1", "step-b", {"result": "done"})

        events = await store.load("wf-1")

        assert len(events) == 2
        assert events[0]["result"] == "ok"
        assert events[0]["step_id"] == "step-a"
        assert events[1]["result"] == "done"
        assert events[1]["step_id"] == "step-b"

    @pytest.mark.asyncio
    async def test_sqlite_load_empty(self, tmp_path: Path) -> None:
        """Load for unknown workflow_id returns empty list."""
        store = SQLiteEventStore(tmp_path / "test.db")

        events = await store.load("nonexistent")

        assert events == []

    @pytest.mark.asyncio
    async def test_sqlite_truncate(self, tmp_path: Path) -> None:
        """Append events, truncate, verify load returns empty."""
        store = SQLiteEventStore(tmp_path / "test.db")

        await store.append("wf-1", "step-a", {"result": "ok"})
        await store.append("wf-1", "step-b", {"result": "done"})
        await store.truncate("wf-1")

        events = await store.load("wf-1")
        assert events == []

    @pytest.mark.asyncio
    async def test_sqlite_truncate_nonexistent(self, tmp_path: Path) -> None:
        """Truncate unknown workflow_id does not raise."""
        store = SQLiteEventStore(tmp_path / "test.db")

        # Should not raise
        await store.truncate("nonexistent")

    @pytest.mark.asyncio
    async def test_sqlite_idempotency_key_dedup(self, tmp_path: Path) -> None:
        """Append same idempotency_key twice, verify only one event stored."""
        store = SQLiteEventStore(tmp_path / "test.db")

        event = {"result": "ok", "idempotency_key": "wf-1:step-a:0"}
        await store.append("wf-1", "step-a", event)
        await store.append("wf-1", "step-a", event)

        events = await store.load("wf-1")
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_sqlite_auto_creates_db(self, tmp_path: Path) -> None:
        """Verify database file created on first operation."""
        db_path = tmp_path / "auto.db"
        assert not db_path.exists()

        store = SQLiteEventStore(db_path)
        await store.append("wf-1", "step-a", {"result": "ok"})

        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_sqlite_persistence_across_instances(self, tmp_path: Path) -> None:
        """Append with one instance, load with a new instance."""
        db_path = tmp_path / "persist.db"

        store1 = SQLiteEventStore(db_path)
        await store1.append("wf-1", "step-a", {"result": "ok"})

        store2 = SQLiteEventStore(db_path)
        events = await store2.load("wf-1")

        assert len(events) == 1
        assert events[0]["result"] == "ok"
        assert events[0]["step_id"] == "step-a"

    @pytest.mark.asyncio
    async def test_sqlite_multiple_workflows_isolated(self, tmp_path: Path) -> None:
        """Events for different workflow_ids are independent."""
        store = SQLiteEventStore(tmp_path / "test.db")

        await store.append("wf-1", "step-a", {"result": "one"})
        await store.append("wf-2", "step-b", {"result": "two"})

        events_1 = await store.load("wf-1")
        events_2 = await store.load("wf-2")

        assert len(events_1) == 1
        assert events_1[0]["result"] == "one"
        assert len(events_2) == 1
        assert events_2[0]["result"] == "two"

        await store.truncate("wf-1")
        assert await store.load("wf-1") == []
        assert len(await store.load("wf-2")) == 1

    @pytest.mark.asyncio
    async def test_sqlite_error_wrapping(self, tmp_path: Path) -> None:
        """Mock sqlite3.connect to raise, verify DurableError raised."""
        store = SQLiteEventStore(tmp_path / "test.db")
        # Force initialization first so the mock only affects append
        await store._ensure_initialized()

        with patch(
            "beddel.adapters.event_store.sqlite3.connect",
            side_effect=sqlite3.OperationalError("disk I/O error"),
        ):
            with pytest.raises(DurableError) as exc_info:
                await store.append("wf-1", "step-a", {"result": "ok"})
            assert exc_info.value.code == DURABLE_WRITE_FAILED

    @pytest.mark.asyncio
    async def test_sqlite_corrupt_data_error(self, tmp_path: Path) -> None:
        """Insert malformed JSON directly, verify DurableError on load."""
        db_path = tmp_path / "corrupt.db"
        store = SQLiteEventStore(db_path)
        # Initialize schema
        await store._ensure_initialized()

        # Insert corrupt data directly via sqlite3
        conn = sqlite3.connect(str(db_path))
        with conn:
            conn.execute(
                "INSERT INTO events "
                "(workflow_id, step_id, idempotency_key, event_data, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("wf-1", "step-a", "wf-1:step-a:0", "NOT-VALID-JSON{{{", 0.0),
            )
        conn.close()

        with pytest.raises(DurableError) as exc_info:
            await store.load("wf-1")
        assert exc_info.value.code == DURABLE_CORRUPT_DATA
