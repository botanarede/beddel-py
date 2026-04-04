"""Tests for InMemoryDecisionStore adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from beddel.adapters.decision_store import InMemoryDecisionStore
from beddel.domain.errors import DecisionError
from beddel.domain.models import Decision
from beddel.error_codes import (
    DECISION_APPEND_FAILED,
    DECISION_DELETE_FAILED,
    DECISION_QUERY_FAILED,
)


def _decision(
    *,
    id: str = "d-1",
    intent: str = "choose model",
    chosen: str = "gpt-4",
    reasoning: str = "best quality",
    workflow_id: str | None = "wf-1",
    step_id: str | None = "step-a",
    timestamp: str | None = "2026-01-15T10:00:00Z",
) -> Decision:
    return Decision(
        id=id,
        intent=intent,
        chosen=chosen,
        reasoning=reasoning,
        workflow_id=workflow_id,
        step_id=step_id,
        timestamp=timestamp,
    )


class TestInMemoryDecisionStoreAppend:
    """Tests for the append method."""

    @pytest.mark.asyncio
    async def test_append_stores_decision(self) -> None:
        store = InMemoryDecisionStore()
        d = _decision()

        await store.append("wf-1", d)

        results = await store.query(workflow_id="wf-1")
        assert len(results) == 1
        assert results[0] is d

    @pytest.mark.asyncio
    async def test_append_multiple_decisions(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", timestamp="2026-01-15T10:00:00Z")
        d2 = _decision(id="d-2", timestamp="2026-01-15T11:00:00Z")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)

        results = await store.query(workflow_id="wf-1")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_append_error_raises_decision_error(self) -> None:
        store = InMemoryDecisionStore()
        # Replace _lock.acquire to force an error inside the try block
        store._lock = AsyncMock()
        store._lock.__aenter__ = AsyncMock(side_effect=RuntimeError("lock broken"))

        with pytest.raises(DecisionError) as exc_info:
            await store.append("wf-1", _decision())
        assert exc_info.value.code == DECISION_APPEND_FAILED


class TestInMemoryDecisionStoreQuery:
    """Tests for the query method."""

    @pytest.mark.asyncio
    async def test_query_empty_store(self) -> None:
        store = InMemoryDecisionStore()

        results = await store.query()
        assert results == []

    @pytest.mark.asyncio
    async def test_query_by_workflow_id(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", workflow_id="wf-1")
        d2 = _decision(id="d-2", workflow_id="wf-2")

        await store.append("wf-1", d1)
        await store.append("wf-2", d2)

        results = await store.query(workflow_id="wf-1")
        assert len(results) == 1
        assert results[0].id == "d-1"

    @pytest.mark.asyncio
    async def test_query_by_step_id(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", step_id="step-a")
        d2 = _decision(id="d-2", step_id="step-b")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)

        results = await store.query(step_id="step-a")
        assert len(results) == 1
        assert results[0].id == "d-1"

    @pytest.mark.asyncio
    async def test_query_by_time_range_since(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", timestamp="2026-01-15T08:00:00Z")
        d2 = _decision(id="d-2", timestamp="2026-01-15T12:00:00Z")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)

        results = await store.query(since="2026-01-15T10:00:00Z")
        assert len(results) == 1
        assert results[0].id == "d-2"

    @pytest.mark.asyncio
    async def test_query_by_time_range_until(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", timestamp="2026-01-15T08:00:00Z")
        d2 = _decision(id="d-2", timestamp="2026-01-15T12:00:00Z")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)

        results = await store.query(until="2026-01-15T10:00:00Z")
        assert len(results) == 1
        assert results[0].id == "d-1"

    @pytest.mark.asyncio
    async def test_query_by_time_range_since_and_until(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", timestamp="2026-01-15T08:00:00Z")
        d2 = _decision(id="d-2", timestamp="2026-01-15T10:00:00Z")
        d3 = _decision(id="d-3", timestamp="2026-01-15T14:00:00Z")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)
        await store.append("wf-1", d3)

        results = await store.query(
            since="2026-01-15T09:00:00Z",
            until="2026-01-15T12:00:00Z",
        )
        assert len(results) == 1
        assert results[0].id == "d-2"

    @pytest.mark.asyncio
    async def test_query_combined_filters(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(
            id="d-1",
            workflow_id="wf-1",
            step_id="step-a",
            timestamp="2026-01-15T10:00:00Z",
        )
        d2 = _decision(
            id="d-2",
            workflow_id="wf-1",
            step_id="step-b",
            timestamp="2026-01-15T11:00:00Z",
        )
        d3 = _decision(
            id="d-3",
            workflow_id="wf-2",
            step_id="step-a",
            timestamp="2026-01-15T10:30:00Z",
        )

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)
        await store.append("wf-2", d3)

        results = await store.query(
            workflow_id="wf-1",
            step_id="step-a",
            since="2026-01-15T09:00:00Z",
            until="2026-01-15T12:00:00Z",
        )
        assert len(results) == 1
        assert results[0].id == "d-1"

    @pytest.mark.asyncio
    async def test_query_no_filters_returns_all(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", timestamp="2026-01-15T10:00:00Z")
        d2 = _decision(id="d-2", timestamp="2026-01-15T11:00:00Z")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)

        results = await store.query()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_sorted_by_timestamp_descending(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", timestamp="2026-01-15T08:00:00Z")
        d2 = _decision(id="d-2", timestamp="2026-01-15T12:00:00Z")
        d3 = _decision(id="d-3", timestamp="2026-01-15T10:00:00Z")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)
        await store.append("wf-1", d3)

        results = await store.query()
        assert [r.id for r in results] == ["d-2", "d-3", "d-1"]

    @pytest.mark.asyncio
    async def test_query_excludes_none_timestamp_from_time_filter(self) -> None:
        """Decisions with timestamp=None are excluded by since/until filters."""
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", timestamp=None)
        d2 = _decision(id="d-2", timestamp="2026-01-15T10:00:00Z")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)

        results = await store.query(since="2026-01-15T09:00:00Z")
        assert len(results) == 1
        assert results[0].id == "d-2"

    @pytest.mark.asyncio
    async def test_query_error_raises_decision_error(self) -> None:
        store = InMemoryDecisionStore()
        store._lock = AsyncMock()
        store._lock.__aenter__ = AsyncMock(side_effect=RuntimeError("lock broken"))

        with pytest.raises(DecisionError) as exc_info:
            await store.query()
        assert exc_info.value.code == DECISION_QUERY_FAILED


class TestInMemoryDecisionStoreDelete:
    """Tests for the delete method."""

    @pytest.mark.asyncio
    async def test_delete_removes_all_for_workflow(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", workflow_id="wf-1")
        d2 = _decision(id="d-2", workflow_id="wf-1")

        await store.append("wf-1", d1)
        await store.append("wf-1", d2)
        await store.delete("wf-1")

        results = await store.query(workflow_id="wf-1")
        assert results == []

    @pytest.mark.asyncio
    async def test_delete_preserves_other_workflows(self) -> None:
        store = InMemoryDecisionStore()
        d1 = _decision(id="d-1", workflow_id="wf-1")
        d2 = _decision(id="d-2", workflow_id="wf-2")

        await store.append("wf-1", d1)
        await store.append("wf-2", d2)
        await store.delete("wf-1")

        results = await store.query(workflow_id="wf-2")
        assert len(results) == 1
        assert results[0].id == "d-2"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_workflow_no_error(self) -> None:
        store = InMemoryDecisionStore()

        # Should not raise
        await store.delete("nonexistent")

    @pytest.mark.asyncio
    async def test_delete_error_raises_decision_error(self) -> None:
        store = InMemoryDecisionStore()
        store._lock = AsyncMock()
        store._lock.__aenter__ = AsyncMock(side_effect=RuntimeError("lock broken"))

        with pytest.raises(DecisionError) as exc_info:
            await store.delete("wf-1")
        assert exc_info.value.code == DECISION_DELETE_FAILED
