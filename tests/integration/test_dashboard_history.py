"""Unit tests for ExecutionHistoryStore (Story D1.3, Task 1)."""

from __future__ import annotations

import concurrent.futures
import datetime
import threading
from typing import Any

from beddel.integrations.dashboard.history import ExecutionHistoryStore, ExecutionRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    run_id: str = "run-1",
    workflow_id: str = "wf-1",
    status: str = "success",
    *,
    events: list[dict[str, Any]] | None = None,
    step_results: list[dict[str, Any]] | None = None,
) -> ExecutionRecord:
    """Create an ExecutionRecord with sensible defaults."""
    return ExecutionRecord(
        run_id=run_id,
        workflow_id=workflow_id,
        status=status,
        started_at=datetime.datetime.now(tz=datetime.UTC),
        events=events or [],
        step_results=step_results or [],
    )


# ---------------------------------------------------------------------------
# ExecutionRecord model tests
# ---------------------------------------------------------------------------


class TestExecutionRecord:
    """Tests for the ExecutionRecord Pydantic model."""

    def test_create_minimal(self) -> None:
        """Record can be created with only required fields."""
        record = _make_record()
        assert record.run_id == "run-1"
        assert record.workflow_id == "wf-1"
        assert record.status == "success"
        assert record.finished_at is None
        assert record.total_duration is None
        assert record.events == []
        assert record.step_results == []

    def test_create_full(self) -> None:
        """Record can be created with all fields populated."""
        now = datetime.datetime.now(tz=datetime.UTC)
        record = ExecutionRecord(
            run_id="run-full",
            workflow_id="wf-full",
            status="success",
            started_at=now,
            finished_at=now + datetime.timedelta(seconds=5),
            total_duration=5.0,
            events=[{"event_type": "workflow_start"}],
            step_results=[{"step_id": "s1", "output": "ok"}],
        )
        assert record.finished_at is not None
        assert record.total_duration == 5.0
        assert len(record.events) == 1
        assert len(record.step_results) == 1

    def test_serialization_roundtrip(self) -> None:
        """Record survives JSON serialization roundtrip."""
        record = _make_record(status="error")
        data = record.model_dump(mode="json")
        restored = ExecutionRecord.model_validate(data)
        assert restored.run_id == record.run_id
        assert restored.status == "error"

    def test_default_status_is_pending(self) -> None:
        """Default status is 'pending' when not specified."""
        record = ExecutionRecord(
            run_id="run-pending",
            workflow_id="wf-pending",
            started_at=datetime.datetime.now(tz=datetime.UTC),
        )
        assert record.status == "pending"


# ---------------------------------------------------------------------------
# ExecutionHistoryStore tests
# ---------------------------------------------------------------------------


class TestExecutionHistoryStore:
    """Tests for the in-memory ExecutionHistoryStore."""

    def test_add_and_get(self) -> None:
        """Add a record and retrieve it by run_id."""
        store = ExecutionHistoryStore()
        record = _make_record(run_id="r1")
        store.add(record)
        result = store.get("r1")
        assert result is not None
        assert result.run_id == "r1"

    def test_get_missing_returns_none(self) -> None:
        """Getting a non-existent run_id returns None."""
        store = ExecutionHistoryStore()
        assert store.get("nonexistent") is None

    def test_list_all(self) -> None:
        """list_all returns all records, newest first."""
        store = ExecutionHistoryStore()
        for i in range(3):
            store.add(_make_record(run_id=f"r{i}"))
        records = store.list_all()
        assert len(records) == 3
        # Newest first (last added = first in list)
        assert records[0].run_id == "r2"
        assert records[2].run_id == "r0"

    def test_list_all_empty(self) -> None:
        """Empty store returns empty list."""
        store = ExecutionHistoryStore()
        assert store.list_all() == []

    def test_fifo_eviction(self) -> None:
        """Oldest record is evicted when max_entries is exceeded."""
        store = ExecutionHistoryStore(max_entries=3)
        for i in range(4):
            store.add(_make_record(run_id=f"r{i}"))
        # r0 should be evicted
        assert store.get("r0") is None
        assert store.get("r1") is not None
        assert store.get("r3") is not None
        assert len(store.list_all()) == 3

    def test_custom_max_entries(self) -> None:
        """Store respects custom max_entries value."""
        store = ExecutionHistoryStore(max_entries=2)
        store.add(_make_record(run_id="a"))
        store.add(_make_record(run_id="b"))
        store.add(_make_record(run_id="c"))
        assert len(store.list_all()) == 2
        assert store.get("a") is None
        assert store.get("c") is not None

    def test_thread_safety(self) -> None:
        """Concurrent adds from multiple threads don't corrupt state."""
        store = ExecutionHistoryStore(max_entries=200)
        barrier = threading.Barrier(10)

        def _add_records(thread_id: int) -> None:
            barrier.wait()
            for i in range(20):
                store.add(_make_record(run_id=f"t{thread_id}-r{i}"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(_add_records, tid) for tid in range(10)]
            for f in futures:
                f.result()

        # 10 threads × 20 records = 200, exactly at cap
        records = store.list_all()
        assert len(records) == 200
        # All run_ids should be unique
        run_ids = [r.run_id for r in records]
        assert len(set(run_ids)) == 200
