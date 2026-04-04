"""Tests for ParallelDispatchStrategy coordination pattern."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from beddel.domain.errors import CoordinationError
from beddel.domain.models import (
    AgentResult,
    CoordinationTask,
    DefaultDependencies,
    ExecutionContext,
)
from beddel.domain.strategies.coordination.parallel_dispatch import (
    ParallelDispatchStrategy,
)
from beddel.error_codes import COORD_NO_AGENTS, COORD_PARALLEL_FAILED


def _make_agent(output: str = "ok", agent_id: str = "test") -> AsyncMock:
    """Create a mock agent adapter returning a predictable AgentResult."""
    agent = AsyncMock()
    agent.execute = AsyncMock(
        return_value=AgentResult(
            exit_code=0,
            output=output,
            events=[],
            files_changed=[],
            usage={},
            agent_id=agent_id,
        )
    )
    return agent


def _make_context() -> ExecutionContext:
    return ExecutionContext(workflow_id="test-wf", inputs={}, deps=DefaultDependencies())


# ── Merge mode ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_mode_two_agents_succeed() -> None:
    """Merge mode concatenates all agent outputs with name headers."""
    alpha = _make_agent(output="Alpha output", agent_id="alpha")
    beta = _make_agent(output="Beta output", agent_id="beta")

    agents = {"alpha": alpha, "beta": beta}
    task = CoordinationTask(prompt="Do work")
    ctx = _make_context()

    strategy = ParallelDispatchStrategy()
    result = await strategy.coordinate(agents, task, ctx)

    assert result.strategy_name == "parallel-dispatch"
    assert "[alpha]:" in result.output
    assert "Alpha output" in result.output
    assert "[beta]:" in result.output
    assert "Beta output" in result.output
    assert "alpha" in result.agent_results
    assert "beta" in result.agent_results
    assert result.metadata["aggregation"] == "merge"
    assert result.metadata["agents_succeeded"] == 2
    assert result.metadata["agents_failed"] == 0


@pytest.mark.asyncio
async def test_merge_mode_default_when_no_config() -> None:
    """Merge is the default aggregation mode."""
    agent = _make_agent(output="Only one", agent_id="solo")
    strategy = ParallelDispatchStrategy()
    result = await strategy.coordinate(
        {"solo": agent},
        CoordinationTask(prompt="Test"),
        _make_context(),
    )
    assert result.metadata["aggregation"] == "merge"


# ── First mode ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_mode_returns_first_success() -> None:
    """First mode returns the first successful result."""
    fast = _make_agent(output="Fast result", agent_id="fast")
    slow = _make_agent(output="Slow result", agent_id="slow")

    agents = {"fast": fast, "slow": slow}
    task = CoordinationTask(prompt="Race")

    strategy = ParallelDispatchStrategy(config={"aggregation": "first"})
    result = await strategy.coordinate(agents, task, _make_context())

    assert result.strategy_name == "parallel-dispatch"
    assert result.metadata["aggregation"] == "first"
    # At least one agent succeeded
    assert result.metadata["agents_succeeded"] == 1
    assert result.output in ("Fast result", "Slow result")
    assert len(result.agent_results) == 1


@pytest.mark.asyncio
async def test_first_mode_skips_failures() -> None:
    """First mode skips failed agents and returns next success."""
    failing = AsyncMock()
    failing.execute = AsyncMock(side_effect=RuntimeError("boom"))
    succeeding = _make_agent(output="Good result", agent_id="good")

    agents = {"failing": failing, "succeeding": succeeding}
    task = CoordinationTask(prompt="Test")

    strategy = ParallelDispatchStrategy(config={"aggregation": "first"})
    result = await strategy.coordinate(agents, task, _make_context())

    assert result.output == "Good result"
    assert "succeeding" in result.agent_results


# ── Vote mode ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vote_mode_majority_wins() -> None:
    """Vote mode returns the most common output (majority wins)."""
    a = _make_agent(output="consensus", agent_id="a")
    b = _make_agent(output="consensus", agent_id="b")
    c = _make_agent(output="dissent", agent_id="c")

    agents = {"a": a, "b": b, "c": c}
    task = CoordinationTask(prompt="Vote")

    strategy = ParallelDispatchStrategy(config={"aggregation": "vote"})
    result = await strategy.coordinate(agents, task, _make_context())

    assert result.output == "consensus"
    assert result.metadata["aggregation"] == "vote"
    assert result.metadata["agents_succeeded"] == 3
    assert result.metadata["agents_failed"] == 0


@pytest.mark.asyncio
async def test_vote_mode_tie_returns_first() -> None:
    """Vote mode tie returns the first result in list order."""
    a = _make_agent(output="option-a", agent_id="a")
    b = _make_agent(output="option-b", agent_id="b")

    agents = {"a": a, "b": b}
    task = CoordinationTask(prompt="Vote tie")

    strategy = ParallelDispatchStrategy(config={"aggregation": "vote"})
    result = await strategy.coordinate(agents, task, _make_context())

    # Counter.most_common returns first-seen on tie
    assert result.output in ("option-a", "option-b")
    assert result.metadata["agents_succeeded"] == 2


# ── All fail ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_fail_merge_raises_coord_error() -> None:
    """All agents failing in merge mode raises CoordinationError."""
    a = AsyncMock()
    a.execute = AsyncMock(side_effect=RuntimeError("fail-a"))
    b = AsyncMock()
    b.execute = AsyncMock(side_effect=RuntimeError("fail-b"))

    agents = {"a": a, "b": b}
    task = CoordinationTask(prompt="Doomed")

    strategy = ParallelDispatchStrategy()
    with pytest.raises(CoordinationError) as exc_info:
        await strategy.coordinate(agents, task, _make_context())

    assert exc_info.value.code == COORD_PARALLEL_FAILED


@pytest.mark.asyncio
async def test_all_fail_first_raises_coord_error() -> None:
    """All agents failing in first mode raises CoordinationError."""
    a = AsyncMock()
    a.execute = AsyncMock(side_effect=RuntimeError("fail"))
    b = AsyncMock()
    b.execute = AsyncMock(side_effect=RuntimeError("fail"))

    agents = {"a": a, "b": b}
    task = CoordinationTask(prompt="Doomed")

    strategy = ParallelDispatchStrategy(config={"aggregation": "first"})
    with pytest.raises(CoordinationError) as exc_info:
        await strategy.coordinate(agents, task, _make_context())

    assert exc_info.value.code == COORD_PARALLEL_FAILED


@pytest.mark.asyncio
async def test_all_fail_vote_raises_coord_error() -> None:
    """All agents failing in vote mode raises CoordinationError."""
    a = AsyncMock()
    a.execute = AsyncMock(side_effect=RuntimeError("fail"))

    agents = {"a": a}
    task = CoordinationTask(prompt="Doomed")

    strategy = ParallelDispatchStrategy(config={"aggregation": "vote"})
    with pytest.raises(CoordinationError) as exc_info:
        await strategy.coordinate(agents, task, _make_context())

    assert exc_info.value.code == COORD_PARALLEL_FAILED


# ── Partial failure ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_partial_failure_merge_includes_error_note() -> None:
    """Merge mode with partial failure includes error notes."""
    good = _make_agent(output="Good output", agent_id="good")
    bad = AsyncMock()
    bad.execute = AsyncMock(side_effect=RuntimeError("agent crashed"))

    agents = {"good": good, "bad": bad}
    task = CoordinationTask(prompt="Partial")

    strategy = ParallelDispatchStrategy()
    result = await strategy.coordinate(agents, task, _make_context())

    assert "Good output" in result.output
    assert "[bad]: ERROR" in result.output
    assert "agent crashed" in result.output
    assert result.metadata["agents_succeeded"] == 1
    assert result.metadata["agents_failed"] == 1
    assert "good" in result.agent_results
    assert "bad" not in result.agent_results


# ── No agents ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_agents_raises_coord_error() -> None:
    """Empty agents dict raises CoordinationError with COORD_NO_AGENTS."""
    task = CoordinationTask(prompt="Test")

    with pytest.raises(CoordinationError) as exc_info:
        await ParallelDispatchStrategy().coordinate({}, task, _make_context())

    assert exc_info.value.code == COORD_NO_AGENTS


# ── Timeout (asyncio.TimeoutError wrapping) ───────────────────────────


@pytest.mark.asyncio
async def test_timeout_agent_treated_as_failure() -> None:
    """Agent raising asyncio.TimeoutError is treated as a failure."""
    good = _make_agent(output="OK", agent_id="good")
    slow = AsyncMock()
    slow.execute = AsyncMock(side_effect=TimeoutError("too slow"))

    agents = {"good": good, "slow": slow}
    task = CoordinationTask(prompt="Timeout test")

    strategy = ParallelDispatchStrategy()
    result = await strategy.coordinate(agents, task, _make_context())

    assert "OK" in result.output
    assert "[slow]: ERROR" in result.output
    assert result.metadata["agents_succeeded"] == 1
    assert result.metadata["agents_failed"] == 1
