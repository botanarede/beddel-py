"""Unit tests for call-agent primitive coordination mode (Story 7.2, Task 5).

Tests the ``coordination`` config key extension: strategy resolution,
agent resolution, CoordinationTask construction, error handling, and
result conversion to dict via ``dataclasses.asdict()``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from beddel.domain.errors import CoordinationError, PrimitiveError
from beddel.domain.models import (
    AgentResult,
    DefaultDependencies,
    ExecutionContext,
)
from beddel.primitives.call_agent import CallAgentPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_result(
    *,
    output: str = "done",
    agent_id: str = "agent-1",
) -> AgentResult:
    return AgentResult(
        exit_code=0,
        output=output,
        events=[],
        files_changed=[],
        usage={},
        agent_id=agent_id,
    )


def _make_mock_agent(
    *,
    output: str = "done",
    agent_id: str = "agent-1",
) -> AsyncMock:
    agent = AsyncMock()
    agent.execute = AsyncMock(
        return_value=_make_agent_result(output=output, agent_id=agent_id),
    )
    return agent


def _make_coordination_context(
    *,
    agent_registry: dict[str, Any] | None = None,
    step_id: str = "step-coord",
) -> ExecutionContext:
    return ExecutionContext(
        workflow_id="wf-coord-test",
        current_step_id=step_id,
        deps=DefaultDependencies(agent_registry=agent_registry),
    )


# ---------------------------------------------------------------------------
# Tests: Supervisor strategy via call-agent (subtask 5.4)
# ---------------------------------------------------------------------------


class TestCoordinationSupervisor:
    """Test call-agent with supervisor coordination strategy."""

    async def test_supervisor_strategy_returns_coordination_result_dict(self) -> None:
        """Verify supervisor coordination returns a dict with expected keys."""
        decomposition_json = '{"assignments": [{"agent": "specialist", "task": "Do analysis"}]}'
        call_count = 0

        async def _supervisor_execute(prompt: str, **kwargs: Any) -> AgentResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_agent_result(output=decomposition_json, agent_id="supervisor")
            return _make_agent_result(output="Final synthesis", agent_id="supervisor")

        supervisor = _make_mock_agent(output="unused", agent_id="supervisor")
        supervisor.execute = AsyncMock(side_effect=_supervisor_execute)
        specialist = _make_mock_agent(output="Specialist result", agent_id="specialist")
        ctx = _make_coordination_context(
            agent_registry={"supervisor": supervisor, "specialist": specialist},
        )

        config: dict[str, Any] = {
            "coordination": {
                "strategy": "supervisor",
                "agents": ["supervisor", "specialist"],
                "prompt": "Analyze the codebase",
            },
        }

        result = await CallAgentPrimitive().execute(config, ctx)

        assert isinstance(result, dict)
        assert "output" in result
        assert "agent_results" in result
        assert "strategy_name" in result
        assert "metadata" in result
        assert result["strategy_name"] == "supervisor"


# ---------------------------------------------------------------------------
# Tests: Handoff strategy via call-agent (subtask 5.4)
# ---------------------------------------------------------------------------


class TestCoordinationHandoff:
    """Test call-agent with handoff coordination strategy."""

    async def test_handoff_strategy_returns_coordination_result_dict(self) -> None:
        """Verify handoff coordination returns a dict with expected keys."""
        agent_a = _make_mock_agent(output="Result from A", agent_id="agent-a")
        agent_b = _make_mock_agent(output="Result from B", agent_id="agent-b")
        ctx = _make_coordination_context(
            agent_registry={"agent-a": agent_a, "agent-b": agent_b},
        )

        config: dict[str, Any] = {
            "coordination": {
                "strategy": "handoff",
                "agents": ["agent-a", "agent-b"],
                "prompt": "Process this request",
                "config": {"max_handoffs": 3},
            },
        }

        result = await CallAgentPrimitive().execute(config, ctx)

        assert isinstance(result, dict)
        assert "output" in result
        assert result["strategy_name"] == "handoff"


# ---------------------------------------------------------------------------
# Tests: Parallel-dispatch strategy via call-agent (subtask 5.4)
# ---------------------------------------------------------------------------


class TestCoordinationParallelDispatch:
    """Test call-agent with parallel-dispatch coordination strategy."""

    async def test_parallel_dispatch_returns_coordination_result_dict(self) -> None:
        """Verify parallel-dispatch coordination returns a dict with expected keys."""
        agent_a = _make_mock_agent(output="Result A", agent_id="agent-a")
        agent_b = _make_mock_agent(output="Result B", agent_id="agent-b")
        ctx = _make_coordination_context(
            agent_registry={"agent-a": agent_a, "agent-b": agent_b},
        )

        config: dict[str, Any] = {
            "coordination": {
                "strategy": "parallel-dispatch",
                "agents": ["agent-a", "agent-b"],
                "prompt": "Analyze this",
                "config": {"aggregation": "merge"},
            },
        }

        result = await CallAgentPrimitive().execute(config, ctx)

        assert isinstance(result, dict)
        assert "output" in result
        assert result["strategy_name"] == "parallel-dispatch"
        assert "agent_results" in result


# ---------------------------------------------------------------------------
# Tests: Error handling (subtask 5.4)
# ---------------------------------------------------------------------------


class TestCoordinationErrors:
    """Test error handling in coordination mode."""

    async def test_missing_strategy_name_raises_prim_error(self) -> None:
        """Verify PrimitiveError when strategy name is missing."""
        ctx = _make_coordination_context(
            agent_registry={"a": _make_mock_agent()},
        )
        config: dict[str, Any] = {
            "coordination": {
                "agents": ["a"],
                "prompt": "Do something",
            },
        }

        with pytest.raises(PrimitiveError, match="strategy") as exc_info:
            await CallAgentPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-001"

    async def test_invalid_strategy_name_raises_prim_error(self) -> None:
        """Verify PrimitiveError when strategy name is not recognized."""
        ctx = _make_coordination_context(
            agent_registry={"a": _make_mock_agent()},
        )
        config: dict[str, Any] = {
            "coordination": {
                "strategy": "nonexistent-strategy",
                "agents": ["a"],
                "prompt": "Do something",
            },
        }

        with pytest.raises(PrimitiveError, match="nonexistent-strategy") as exc_info:
            await CallAgentPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-001"

    async def test_missing_agent_registry_raises_prim_error(self) -> None:
        """Verify PrimitiveError when agent_registry is None."""
        ctx = _make_coordination_context(agent_registry=None)
        config: dict[str, Any] = {
            "coordination": {
                "strategy": "supervisor",
                "agents": ["a"],
                "prompt": "Do something",
            },
        }

        with pytest.raises(PrimitiveError, match="agent_registry") as exc_info:
            await CallAgentPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-001"

    async def test_agent_not_found_in_registry_raises_prim_error(self) -> None:
        """Verify PrimitiveError when an agent name is not in the registry."""
        ctx = _make_coordination_context(
            agent_registry={"existing": _make_mock_agent()},
        )
        config: dict[str, Any] = {
            "coordination": {
                "strategy": "supervisor",
                "agents": ["existing", "missing-agent"],
                "prompt": "Do something",
            },
        }

        with pytest.raises(PrimitiveError, match="missing-agent") as exc_info:
            await CallAgentPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-001"

    async def test_coordination_error_re_raised_as_is(self) -> None:
        """Verify CoordinationError from strategy is re-raised directly."""
        agent_a = _make_mock_agent(output="ok", agent_id="a")
        agent_b = _make_mock_agent(output="ok", agent_id="b")
        ctx = _make_coordination_context(
            agent_registry={"a": agent_a, "b": agent_b},
        )

        # Make the strategy itself raise CoordinationError by providing
        # an empty agents list in coordination config (agents resolved to
        # empty dict triggers COORD_NO_AGENTS inside the strategy).
        config: dict[str, Any] = {
            "coordination": {
                "strategy": "parallel-dispatch",
                "agents": [],
                "prompt": "Do something",
            },
        }

        with pytest.raises(CoordinationError, match="No agents configured"):
            await CallAgentPrimitive().execute(config, ctx)

    async def test_unexpected_error_wrapped_in_prim_error(self) -> None:
        """Verify non-CoordinationError exceptions are wrapped in PrimitiveError."""
        agent = _make_mock_agent()
        ctx = _make_coordination_context(
            agent_registry={"a": agent},
        )

        # Patch the strategy's coordinate method to raise a raw exception
        from unittest.mock import patch

        with patch(
            "beddel.primitives.call_agent.ParallelDispatchStrategy.coordinate",
            side_effect=RuntimeError("unexpected boom"),
        ):
            config: dict[str, Any] = {
                "coordination": {
                    "strategy": "parallel-dispatch",
                    "agents": ["a"],
                    "prompt": "Do something",
                },
            }

            with pytest.raises(PrimitiveError, match="Coordination failed"):
                await CallAgentPrimitive().execute(config, ctx)


# ---------------------------------------------------------------------------
# Tests: Backward compatibility — no coordination key (subtask 5.4)
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Verify call-agent still works without coordination key."""

    async def test_without_coordination_requires_workflow_key(self) -> None:
        """Without coordination, missing workflow raises PRIM-201."""
        ctx = _make_coordination_context(
            agent_registry={"a": _make_mock_agent()},
        )

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-201"):
            await CallAgentPrimitive().execute({}, ctx)
