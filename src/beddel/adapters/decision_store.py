"""Decision store adapter for structured decision persistence.

Provides :class:`InMemoryDecisionStore` — an in-memory
:class:`~beddel.domain.ports.IDecisionStore` implementation that stores
decisions in a flat list with optional filtering by workflow_id, step_id,
and ISO 8601 time range.
"""

from __future__ import annotations

import asyncio

from beddel.domain.errors import DecisionError
from beddel.domain.models import Decision
from beddel.error_codes import (
    DECISION_APPEND_FAILED,
    DECISION_DELETE_FAILED,
    DECISION_QUERY_FAILED,
)


class InMemoryDecisionStore:
    """In-memory decision store backed by a flat list.

    Satisfies the :class:`~beddel.domain.ports.IDecisionStore` protocol
    via structural subtyping.

    Decisions are stored in insertion order and returned newest-first
    (descending timestamp) from :meth:`query`.
    """

    def __init__(self) -> None:
        self._decisions: list[Decision] = []
        self._lock = asyncio.Lock()

    async def append(self, workflow_id: str, decision: Decision) -> None:
        """Append a decision for a workflow.

        Args:
            workflow_id: Identifier of the workflow execution.
            decision: The decision to persist.
        """
        try:
            async with self._lock:
                self._decisions.append(decision)
        except DecisionError:
            raise
        except Exception as exc:
            raise DecisionError(
                DECISION_APPEND_FAILED,
                f"Failed to append decision for workflow {workflow_id!r}: {exc}",
            ) from exc

    async def query(
        self,
        workflow_id: str | None = None,
        step_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> list[Decision]:
        """Query decisions with optional filters.

        Args:
            workflow_id: Filter by workflow identifier.
            step_id: Filter by step identifier.
            since: Filter decisions at or after this ISO 8601 timestamp.
            until: Filter decisions at or before this ISO 8601 timestamp.

        Returns:
            Matching decisions sorted by timestamp descending.
        """
        try:
            async with self._lock:
                results = list(self._decisions)

            if workflow_id is not None:
                results = [d for d in results if d.workflow_id == workflow_id]
            if step_id is not None:
                results = [d for d in results if d.step_id == step_id]
            if since is not None:
                results = [d for d in results if d.timestamp is not None and d.timestamp >= since]
            if until is not None:
                results = [d for d in results if d.timestamp is not None and d.timestamp <= until]

            return sorted(
                results,
                key=lambda d: d.timestamp or "",
                reverse=True,
            )
        except DecisionError:
            raise
        except Exception as exc:
            raise DecisionError(
                DECISION_QUERY_FAILED,
                f"Failed to query decisions: {exc}",
            ) from exc

    async def delete(self, workflow_id: str) -> None:
        """Remove all decisions for a workflow.

        Args:
            workflow_id: Identifier of the workflow execution to clear.
        """
        try:
            async with self._lock:
                self._decisions = [d for d in self._decisions if d.workflow_id != workflow_id]
        except DecisionError:
            raise
        except Exception as exc:
            raise DecisionError(
                DECISION_DELETE_FAILED,
                f"Failed to delete decisions for workflow {workflow_id!r}: {exc}",
            ) from exc
