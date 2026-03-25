"""In-memory bounded execution history store.

Provides :class:`ExecutionRecord` (Pydantic model) and
:class:`ExecutionHistoryStore` for tracking workflow execution history
with thread-safe FIFO eviction.
"""

from __future__ import annotations

import datetime
import threading
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, Field

__all__ = ["ExecutionHistoryStore", "ExecutionRecord"]


class ExecutionRecord(BaseModel):
    """A single workflow execution record.

    Attributes:
        run_id: Unique identifier for this execution run.
        workflow_id: Identifier of the workflow that was executed.
        status: Current execution status (e.g. ``"pending"``, ``"success"``,
            ``"error"``).
        started_at: UTC timestamp when execution started.
        finished_at: UTC timestamp when execution finished, if complete.
        total_duration: Total execution duration in milliseconds, if complete.
        events: List of event dicts captured during execution.
        step_results: List of step result dicts from execution.
    """

    run_id: str
    workflow_id: str
    status: str = "pending"
    started_at: datetime.datetime
    finished_at: datetime.datetime | None = None
    total_duration: float | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    step_results: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionHistoryStore:
    """Thread-safe in-memory bounded store for execution records.

    Uses an :class:`~collections.OrderedDict` for O(1) insertion-order
    tracking and FIFO eviction when ``max_entries`` is reached.

    Args:
        max_entries: Maximum number of records to retain. Defaults to 100.

    Example::

        store = ExecutionHistoryStore(max_entries=50)
        store.add(record)
        latest = store.list_all()  # newest first
    """

    def __init__(self, max_entries: int = 100) -> None:
        self._max_entries = max_entries
        self._records: OrderedDict[str, ExecutionRecord] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, record: ExecutionRecord) -> None:
        """Add an execution record to the store.

        If the store is at capacity, the oldest record is evicted (FIFO).

        Args:
            record: The execution record to store.
        """
        with self._lock:
            self._records[record.run_id] = record
            while len(self._records) > self._max_entries:
                self._records.popitem(last=False)

    def get(self, run_id: str) -> ExecutionRecord | None:
        """Retrieve an execution record by run ID.

        Args:
            run_id: The unique run identifier to look up.

        Returns:
            The matching record, or ``None`` if not found.
        """
        with self._lock:
            return self._records.get(run_id)

    def list_all(self) -> list[ExecutionRecord]:
        """Return all stored records, newest first.

        Returns:
            List of execution records ordered from newest to oldest.
        """
        with self._lock:
            return list(reversed(self._records.values()))
