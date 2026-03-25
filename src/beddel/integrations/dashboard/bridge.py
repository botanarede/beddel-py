"""Dashboard SSE bridge — connects WorkflowExecutor streaming to SSE.

Provides :class:`DashboardSSEBridge`, which orchestrates workflow execution
via a :class:`~beddel.domain.executor.WorkflowExecutor`, pipes the event
stream through :class:`~beddel.integrations.sse.BeddelSSEAdapter`, and
records execution history in an
:class:`~beddel.integrations.dashboard.history.ExecutionHistoryStore`.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import Workflow
from beddel.integrations.dashboard.history import ExecutionHistoryStore, ExecutionRecord
from beddel.integrations.sse import BeddelSSEAdapter

__all__ = ["DashboardSSEBridge"]


class DashboardSSEBridge:
    """Bridge between WorkflowExecutor streaming and SSE delivery.

    Receives a :class:`WorkflowExecutor` and an
    :class:`ExecutionHistoryStore` via dependency injection.  The
    :meth:`execute_and_stream` method seeds an execution record, starts
    streaming, and returns a ``(run_id, sse_stream)`` tuple.  The stream
    tees events: one branch yields SSE dicts to the caller, the other
    collects them for the history store on completion.

    Args:
        executor: The workflow executor that provides ``execute_stream``.
        history: The execution history store for recording runs.

    Example::

        bridge = DashboardSSEBridge(executor=my_executor, history=store)
        run_id, stream = await bridge.execute_and_stream(workflow)
        async for sse_dict in stream:
            ...  # send to client
    """

    def __init__(
        self,
        executor: WorkflowExecutor,
        history: ExecutionHistoryStore,
    ) -> None:
        self._executor = executor
        self._history = history

    async def execute_and_stream(
        self,
        workflow: Workflow,
        inputs: dict[str, Any] | None = None,
    ) -> tuple[str, AsyncGenerator[dict[str, str], None]]:
        """Execute a workflow and return (run_id, sse_stream).

        Seeds an :class:`ExecutionRecord` in the history store with status
        ``"running"``, then returns an async generator that yields SSE dicts.
        The generator collects events and updates the history record on
        completion (or error).

        Args:
            workflow: The workflow definition to execute.
            inputs: Optional input dict forwarded to the executor.

        Returns:
            A tuple of ``(run_id, sse_stream)`` where ``run_id`` is a UUID4
            string and ``sse_stream`` is an async generator yielding SSE
            dicts with ``event`` and ``data`` keys.
        """
        run_id = str(uuid.uuid4())
        now = datetime.datetime.now(tz=datetime.UTC)
        record = ExecutionRecord(
            run_id=run_id,
            workflow_id=workflow.id,
            status="running",
            started_at=now,
        )
        self._history.add(record)

        async def _stream() -> AsyncGenerator[dict[str, str], None]:
            collected_events: list[dict[str, Any]] = []
            status = "success"
            try:
                raw_events = self._executor.execute_stream(workflow, inputs)
                sse_events = BeddelSSEAdapter.stream_events(raw_events)
                async for sse_dict in sse_events:
                    collected_events.append(sse_dict)
                    yield sse_dict
                    if sse_dict.get("event") == "error":
                        status = "error"
            except Exception:
                status = "error"
                raise
            finally:
                finished = datetime.datetime.now(tz=datetime.UTC)
                duration_ms = (finished - now).total_seconds() * 1000
                updated = ExecutionRecord(
                    run_id=run_id,
                    workflow_id=workflow.id,
                    status=status,
                    started_at=now,
                    finished_at=finished,
                    total_duration=duration_ms,
                    events=collected_events,
                )
                self._history.add(updated)

        return run_id, _stream()
