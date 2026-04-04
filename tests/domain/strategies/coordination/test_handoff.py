"""Tests for HandoffStrategy coordination pattern."""

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
from beddel.domain.strategies.coordination.handoff import HandoffStrategy
from beddel.error_codes import COORD_HANDOFF_FAILED, COORD_NO_AGENTS


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


# ── Single handoff ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_handoff() -> None:
    """Agent A hands off to agent B, B returns final result."""
    agent_a = _make_agent(output="Result A __handoff__:B", agent_id="A")
    agent_b = _make_agent(output="Final B", agent_id="B")

    agents = {"A": agent_a, "B": agent_b}
    task = CoordinationTask(prompt="Do work")
    ctx = _make_context()

    strategy = HandoffStrategy()
    result = await strategy.coordinate(agents, task, ctx)

    assert result.output == "Final B"
    assert result.strategy_name == "handoff"
    assert result.metadata["chain"] == ["A", "B"]
    assert result.metadata["handoff_count"] == 1
    assert "A" in result.agent_results
    assert "B" in result.agent_results


# ── Chain of 3 agents ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_of_three_agents() -> None:
    """A → B → C handoff chain produces correct final output."""
    agent_a = _make_agent(output="From A __handoff__:B", agent_id="A")
    agent_b = _make_agent(output="From B __handoff__:C", agent_id="B")
    agent_c = _make_agent(output="Final C", agent_id="C")

    agents = {"A": agent_a, "B": agent_b, "C": agent_c}
    task = CoordinationTask(prompt="Chain task")

    result = await HandoffStrategy().coordinate(agents, task, _make_context())

    assert result.output == "Final C"
    assert result.metadata["chain"] == ["A", "B", "C"]
    assert result.metadata["handoff_count"] == 2
    assert set(result.agent_results.keys()) == {"A", "B", "C"}


# ── Max handoffs exceeded ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_max_handoffs_exceeded() -> None:
    """Exceeding max_handoffs raises CoordinationError."""
    # Create agents that always hand off in a loop: A → B → A → B → ...
    agent_a = _make_agent(output="A output __handoff__:B", agent_id="A")
    agent_b = _make_agent(output="B output __handoff__:A", agent_id="B")

    agents = {"A": agent_a, "B": agent_b}
    task = CoordinationTask(prompt="Loop task")

    strategy = HandoffStrategy(config={"max_handoffs": 2})

    with pytest.raises(CoordinationError) as exc_info:
        await strategy.coordinate(agents, task, _make_context())

    assert exc_info.value.code == COORD_HANDOFF_FAILED


# ── No handoff (direct return) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_handoff_direct_return() -> None:
    """Agent output without handoff marker returns directly."""
    agent_a = _make_agent(output="Direct result", agent_id="A")

    agents = {"A": agent_a}
    task = CoordinationTask(prompt="Simple task")

    result = await HandoffStrategy().coordinate(agents, task, _make_context())

    assert result.output == "Direct result"
    assert result.metadata["chain"] == ["A"]
    assert result.metadata["handoff_count"] == 0
    assert "A" in result.agent_results


# ── Context accumulation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_accumulation() -> None:
    """Agent B receives agent A's output in its prompt."""
    agent_a = _make_agent(output="Analysis done __handoff__:B", agent_id="A")
    agent_b = _make_agent(output="Final synthesis", agent_id="B")

    agents = {"A": agent_a, "B": agent_b}
    task = CoordinationTask(prompt="Analyze and synthesize")

    await HandoffStrategy().coordinate(agents, task, _make_context())

    # Verify agent B received the accumulated context
    b_call = agent_b.execute.call_args
    b_prompt: str = b_call.args[0]
    assert "Analyze and synthesize" in b_prompt
    assert "Previous agent outputs:" in b_prompt
    assert "[A]: Analysis done" in b_prompt


@pytest.mark.asyncio
async def test_context_accumulation_three_agents() -> None:
    """Agent C receives outputs from both A and B."""
    agent_a = _make_agent(output="Step 1 __handoff__:B", agent_id="A")
    agent_b = _make_agent(output="Step 2 __handoff__:C", agent_id="B")
    agent_c = _make_agent(output="Step 3 done", agent_id="C")

    agents = {"A": agent_a, "B": agent_b, "C": agent_c}
    task = CoordinationTask(prompt="Multi-step")

    await HandoffStrategy().coordinate(agents, task, _make_context())

    c_call = agent_c.execute.call_args
    c_prompt: str = c_call.args[0]
    assert "[A]: Step 1" in c_prompt
    assert "[B]: Step 2" in c_prompt


# ── No agents ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_agents_raises_coord_error() -> None:
    """Empty agents dict raises CoordinationError with COORD_NO_AGENTS."""
    task = CoordinationTask(prompt="Test")

    with pytest.raises(CoordinationError) as exc_info:
        await HandoffStrategy().coordinate({}, task, _make_context())

    assert exc_info.value.code == COORD_NO_AGENTS


# ── Agent not found ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handoff_to_unknown_agent_raises() -> None:
    """Handoff to non-existent agent raises CoordinationError."""
    agent_a = _make_agent(output="Going to ghost __handoff__:ghost", agent_id="A")

    agents = {"A": agent_a}
    task = CoordinationTask(prompt="Test")

    with pytest.raises(CoordinationError) as exc_info:
        await HandoffStrategy().coordinate(agents, task, _make_context())

    assert exc_info.value.code == COORD_HANDOFF_FAILED


# ── First agent from subtasks ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_agent_from_subtasks() -> None:
    """When task.subtasks is provided, first entry is the starting agent."""
    agent_a = _make_agent(output="A result", agent_id="A")
    agent_b = _make_agent(output="B result", agent_id="B")

    agents = {"A": agent_a, "B": agent_b}
    task = CoordinationTask(prompt="Test", subtasks=["B"])

    result = await HandoffStrategy().coordinate(agents, task, _make_context())

    assert result.output == "B result"
    assert result.metadata["chain"] == ["B"]
    # Agent A was never called
    agent_a.execute.assert_not_called()


# ── Handoff marker stripped from output ───────────────────────────────


@pytest.mark.asyncio
async def test_handoff_marker_stripped_from_context() -> None:
    """The __handoff__ marker is stripped before passing context."""
    agent_a = _make_agent(output="Clean text __handoff__:B", agent_id="A")
    agent_b = _make_agent(output="Done", agent_id="B")

    agents = {"A": agent_a, "B": agent_b}
    task = CoordinationTask(prompt="Test")

    await HandoffStrategy().coordinate(agents, task, _make_context())

    b_prompt: str = agent_b.execute.call_args.args[0]
    assert "__handoff__" not in b_prompt
    assert "[A]: Clean text" in b_prompt
