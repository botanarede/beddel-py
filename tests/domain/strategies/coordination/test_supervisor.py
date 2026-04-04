"""Tests for SupervisorStrategy coordination pattern."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from beddel.domain.errors import CoordinationError
from beddel.domain.models import (
    AgentResult,
    CoordinationTask,
    DefaultDependencies,
    ExecutionContext,
)
from beddel.domain.strategies.coordination.supervisor import SupervisorStrategy
from beddel.error_codes import (
    COORD_NO_AGENTS,
    COORD_STRATEGY_FAILED,
    COORD_SUPERVISOR_FAILED,
)


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


def _decomposition_json(assignments: list[dict[str, str]]) -> str:
    return json.dumps({"assignments": assignments})


# ── Basic delegation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_basic_delegation() -> None:
    """Supervisor decomposes, dispatches to specialists, and synthesizes."""
    supervisor_agent = _make_agent(agent_id="supervisor")
    # First call: decomposition → return JSON assignments
    decomposition = _decomposition_json(
        [
            {"agent": "writer", "task": "Write the intro"},
            {"agent": "reviewer", "task": "Review the intro"},
        ]
    )
    supervisor_agent.execute = AsyncMock(
        side_effect=[
            AgentResult(0, decomposition, [], [], {}, "supervisor"),
            AgentResult(0, "Final synthesized output", [], [], {}, "supervisor"),
        ]
    )
    writer = _make_agent(output="Intro written", agent_id="writer")
    reviewer = _make_agent(output="Looks good", agent_id="reviewer")

    agents = {
        "supervisor": supervisor_agent,
        "writer": writer,
        "reviewer": reviewer,
    }
    task = CoordinationTask(prompt="Write and review an intro")
    ctx = _make_context()

    strategy = SupervisorStrategy()
    result = await strategy.coordinate(agents, task, ctx)

    assert result.output == "Final synthesized output"
    assert result.strategy_name == "supervisor"
    assert "writer" in result.agent_results
    assert "reviewer" in result.agent_results
    assert result.agent_results["writer"].output == "Intro written"
    assert result.agent_results["reviewer"].output == "Looks good"
    # Supervisor called twice: decompose + synthesize
    assert supervisor_agent.execute.call_count == 2


# ── Supervisor selection ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uses_supervisor_key_when_present() -> None:
    """When 'supervisor' key exists, that agent is used as supervisor."""
    decomposition = _decomposition_json([{"agent": "worker", "task": "Do work"}])
    sup = _make_agent(agent_id="sup")
    sup.execute = AsyncMock(
        side_effect=[
            AgentResult(0, decomposition, [], [], {}, "sup"),
            AgentResult(0, "Done", [], [], {}, "sup"),
        ]
    )
    worker = _make_agent(output="Work done", agent_id="worker")

    agents = {"worker": worker, "supervisor": sup}
    task = CoordinationTask(prompt="Do something")
    result = await SupervisorStrategy().coordinate(agents, task, _make_context())

    assert result.output == "Done"
    assert sup.execute.call_count == 2


@pytest.mark.asyncio
async def test_uses_first_agent_when_no_supervisor_key() -> None:
    """When no 'supervisor' key, the first agent acts as supervisor."""
    decomposition = _decomposition_json([{"agent": "beta", "task": "Beta task"}])
    alpha = _make_agent(agent_id="alpha")
    alpha.execute = AsyncMock(
        side_effect=[
            AgentResult(0, decomposition, [], [], {}, "alpha"),
            AgentResult(0, "Alpha synthesized", [], [], {}, "alpha"),
        ]
    )
    beta = _make_agent(output="Beta result", agent_id="beta")

    agents = {"alpha": alpha, "beta": beta}
    task = CoordinationTask(prompt="Test")
    result = await SupervisorStrategy().coordinate(agents, task, _make_context())

    assert result.output == "Alpha synthesized"
    assert alpha.execute.call_count == 2


# ── Decomposition failure ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decomposition_failure_raises_coord_error() -> None:
    """Non-JSON garbage from supervisor raises CoordinationError."""
    sup = _make_agent(output="This is not JSON at all!", agent_id="sup")
    agents = {"supervisor": sup}
    task = CoordinationTask(prompt="Decompose this")

    with pytest.raises(CoordinationError) as exc_info:
        await SupervisorStrategy().coordinate(agents, task, _make_context())

    assert exc_info.value.code == COORD_SUPERVISOR_FAILED


@pytest.mark.asyncio
async def test_decomposition_empty_assignments_raises() -> None:
    """JSON with empty assignments list raises CoordinationError."""
    sup = _make_agent(output='{"assignments": []}', agent_id="sup")
    agents = {"supervisor": sup}
    task = CoordinationTask(prompt="Decompose this")

    with pytest.raises(CoordinationError) as exc_info:
        await SupervisorStrategy().coordinate(agents, task, _make_context())

    assert exc_info.value.code == COORD_SUPERVISOR_FAILED


# ── Agent not found ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_not_found_skipped_gracefully() -> None:
    """Assignment to non-existent agent is skipped, not failed."""
    decomposition = _decomposition_json(
        [
            {"agent": "existing", "task": "Do work"},
            {"agent": "ghost", "task": "Ghost work"},
        ]
    )
    sup = _make_agent(agent_id="sup")
    sup.execute = AsyncMock(
        side_effect=[
            AgentResult(0, decomposition, [], [], {}, "sup"),
            AgentResult(0, "Synthesized", [], [], {}, "sup"),
        ]
    )
    existing = _make_agent(output="Existing result", agent_id="existing")

    agents = {"supervisor": sup, "existing": existing}
    task = CoordinationTask(prompt="Test")
    result = await SupervisorStrategy().coordinate(agents, task, _make_context())

    assert "existing" in result.agent_results
    assert "ghost" not in result.agent_results
    assert result.output == "Synthesized"


# ── No agents ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_agents_raises_coord_error() -> None:
    """Empty agents dict raises CoordinationError with COORD_NO_AGENTS."""
    task = CoordinationTask(prompt="Test")

    with pytest.raises(CoordinationError) as exc_info:
        await SupervisorStrategy().coordinate({}, task, _make_context())

    assert exc_info.value.code == COORD_NO_AGENTS


# ── Synthesis ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthesis_receives_all_agent_results() -> None:
    """Supervisor synthesis prompt includes all agent outputs."""
    decomposition = _decomposition_json(
        [{"agent": "a", "task": "Task A"}, {"agent": "b", "task": "Task B"}]
    )
    sup = _make_agent(agent_id="sup")
    sup.execute = AsyncMock(
        side_effect=[
            AgentResult(0, decomposition, [], [], {}, "sup"),
            AgentResult(0, "Combined A+B", [], [], {}, "sup"),
        ]
    )
    a = _make_agent(output="Result A", agent_id="a")
    b = _make_agent(output="Result B", agent_id="b")

    agents = {"supervisor": sup, "a": a, "b": b}
    task = CoordinationTask(prompt="Combine")
    result = await SupervisorStrategy().coordinate(agents, task, _make_context())

    # Verify synthesis call includes agent outputs
    synthesis_call = sup.execute.call_args_list[1]
    synthesis_prompt = synthesis_call.args[0]
    assert "Result A" in synthesis_prompt
    assert "Result B" in synthesis_prompt
    assert result.output == "Combined A+B"


# ── General failure wrapping ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_general_exception_wrapped_as_strategy_failed() -> None:
    """Unexpected exceptions are wrapped in COORD_STRATEGY_FAILED."""
    sup = _make_agent(agent_id="sup")
    sup.execute = AsyncMock(side_effect=RuntimeError("boom"))

    agents = {"supervisor": sup}
    task = CoordinationTask(prompt="Test")

    with pytest.raises(CoordinationError) as exc_info:
        await SupervisorStrategy().coordinate(agents, task, _make_context())

    assert exc_info.value.code == COORD_STRATEGY_FAILED


# ── JSON embedded in markdown fences ──────────────────────────────────


@pytest.mark.asyncio
async def test_json_embedded_in_text_parsed() -> None:
    """JSON embedded in surrounding text is still extracted."""
    inner_json = _decomposition_json([{"agent": "worker", "task": "Do it"}])
    output_with_fences = f"Here is the plan:\n```json\n{inner_json}\n```"
    sup = _make_agent(agent_id="sup")
    sup.execute = AsyncMock(
        side_effect=[
            AgentResult(0, output_with_fences, [], [], {}, "sup"),
            AgentResult(0, "Final", [], [], {}, "sup"),
        ]
    )
    worker = _make_agent(output="Done", agent_id="worker")

    agents = {"supervisor": sup, "worker": worker}
    task = CoordinationTask(prompt="Test")
    result = await SupervisorStrategy().coordinate(agents, task, _make_context())

    assert result.output == "Final"
    assert "worker" in result.agent_results


# ── Metadata ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_result_metadata_contains_assignments() -> None:
    """CoordinationResult metadata includes assignment mapping."""
    decomposition = _decomposition_json([{"agent": "w", "task": "Work"}])
    sup = _make_agent(agent_id="sup")
    sup.execute = AsyncMock(
        side_effect=[
            AgentResult(0, decomposition, [], [], {}, "sup"),
            AgentResult(0, "Done", [], [], {}, "sup"),
        ]
    )
    w = _make_agent(output="Worked", agent_id="w")

    agents = {"supervisor": sup, "w": w}
    task = CoordinationTask(prompt="Test")
    result = await SupervisorStrategy().coordinate(agents, task, _make_context())

    assert "assignments" in result.metadata
    assert result.metadata["assignments"] == {"w": "Work"}
    assert result.metadata["agents_used"] == ["w"]
