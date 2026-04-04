"""Integration tests for multi-agent coordination (Story 7.2, Task 5).

Full pipeline: create ExecutionContext with mock agents + coordination
strategy → execute call-agent step → verify CoordinationResult dict.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from beddel.domain.models import (
    AgentResult,
    DefaultDependencies,
    ExecutionContext,
    Workflow,
)
from beddel.domain.parser import WorkflowParser
from beddel.primitives.call_agent import CallAgentPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_VALID_DIR = _REPO_ROOT / "spec" / "fixtures" / "valid"


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


def _make_integration_context(
    *,
    agent_registry: dict[str, Any],
) -> ExecutionContext:
    return ExecutionContext(
        workflow_id="wf-integration-coord",
        current_step_id="step-coord",
        deps=DefaultDependencies(agent_registry=agent_registry),
    )


# ---------------------------------------------------------------------------
# Integration: Full pipeline (subtask 5.6)
# ---------------------------------------------------------------------------


class TestCoordinationPipeline:
    """Full pipeline: call-agent primitive → strategy → result dict."""

    async def test_supervisor_full_pipeline(self) -> None:
        """Execute call-agent with supervisor strategy, verify result structure."""
        # Supervisor returns JSON assignments on first call, synthesis on second
        decomposition_json = '{"assignments": [{"agent": "specialist", "task": "Analyze code"}]}'
        supervisor = AsyncMock()
        call_count = 0

        async def _supervisor_execute(prompt: str, **kwargs: Any) -> AgentResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_agent_result(output=decomposition_json, agent_id="supervisor")
            return _make_agent_result(output="Synthesized output", agent_id="supervisor")

        supervisor.execute = AsyncMock(side_effect=_supervisor_execute)
        specialist = _make_mock_agent(output="Specialist analysis", agent_id="specialist")
        ctx = _make_integration_context(
            agent_registry={"supervisor": supervisor, "specialist": specialist},
        )

        config: dict[str, Any] = {
            "coordination": {
                "strategy": "supervisor",
                "agents": ["supervisor", "specialist"],
                "prompt": "Analyze the codebase thoroughly",
            },
        }

        result = await CallAgentPrimitive().execute(config, ctx)

        assert isinstance(result, dict)
        assert "output" in result
        assert "agent_results" in result
        assert "strategy_name" in result
        assert "metadata" in result
        assert result["strategy_name"] == "supervisor"
        assert isinstance(result["agent_results"], dict)

    async def test_parallel_dispatch_full_pipeline(self) -> None:
        """Execute call-agent with parallel-dispatch, verify merged output."""
        agent_a = _make_mock_agent(output="Analysis A", agent_id="agent-a")
        agent_b = _make_mock_agent(output="Analysis B", agent_id="agent-b")
        ctx = _make_integration_context(
            agent_registry={"agent-a": agent_a, "agent-b": agent_b},
        )

        config: dict[str, Any] = {
            "coordination": {
                "strategy": "parallel-dispatch",
                "agents": ["agent-a", "agent-b"],
                "prompt": "Analyze this code",
                "config": {"aggregation": "merge"},
            },
        }

        result = await CallAgentPrimitive().execute(config, ctx)

        assert isinstance(result, dict)
        assert result["strategy_name"] == "parallel-dispatch"
        assert "agent-a" in result["agent_results"]
        assert "agent-b" in result["agent_results"]
        # Merged output should contain both agent outputs
        assert "Analysis A" in result["output"]
        assert "Analysis B" in result["output"]

    async def test_handoff_full_pipeline(self) -> None:
        """Execute call-agent with handoff strategy, verify result."""
        agent_a = _make_mock_agent(output="Processed by A", agent_id="agent-a")
        agent_b = _make_mock_agent(output="Processed by B", agent_id="agent-b")
        ctx = _make_integration_context(
            agent_registry={"agent-a": agent_a, "agent-b": agent_b},
        )

        config: dict[str, Any] = {
            "coordination": {
                "strategy": "handoff",
                "agents": ["agent-a", "agent-b"],
                "prompt": "Process this request",
            },
        }

        result = await CallAgentPrimitive().execute(config, ctx)

        assert isinstance(result, dict)
        assert result["strategy_name"] == "handoff"
        assert "output" in result

    async def test_coordination_result_has_all_required_keys(self) -> None:
        """Verify the result dict has output, agent_results, strategy_name, metadata."""
        agent = _make_mock_agent(output="Result", agent_id="solo")
        ctx = _make_integration_context(
            agent_registry={"solo": agent},
        )

        config: dict[str, Any] = {
            "coordination": {
                "strategy": "parallel-dispatch",
                "agents": ["solo"],
                "prompt": "Do work",
            },
        }

        result = await CallAgentPrimitive().execute(config, ctx)

        required_keys = {"output", "agent_results", "strategy_name", "metadata"}
        assert required_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Spec fixture: multi-agent-coordination.yaml (subtask 5.5)
# ---------------------------------------------------------------------------


class TestMultiAgentCoordinationFixture:
    """Spec fixture multi-agent-coordination.yaml parses and validates."""

    def test_fixture_parses_to_workflow(self) -> None:
        yaml_str = (_VALID_DIR / "multi-agent-coordination.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert isinstance(wf, Workflow)

    def test_workflow_id_and_name(self) -> None:
        yaml_str = (_VALID_DIR / "multi-agent-coordination.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert wf.id == "multi-agent-coordination"
        assert wf.name == "Multi-Agent Coordination Workflow"

    def test_coordination_step_present(self) -> None:
        yaml_str = (_VALID_DIR / "multi-agent-coordination.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert len(wf.steps) == 1
        step = wf.steps[0]
        assert step.id == "coordinate-agents"
        assert step.primitive == "call-agent"

    def test_coordination_config_preserved(self) -> None:
        yaml_str = (_VALID_DIR / "multi-agent-coordination.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        config = wf.steps[0].config
        coord = config["coordination"]
        assert coord["strategy"] == "supervisor"
        assert coord["agents"] == ["codex", "claude"]
        assert coord["config"]["max_handoffs"] == 3
        assert coord["prompt"] == "$input.task_description"
        assert coord["subtasks"] == ["Analyze code structure", "Review documentation"]
        assert coord["context_data"]["project"] == "beddel"

    def test_input_schema_present(self) -> None:
        yaml_str = (_VALID_DIR / "multi-agent-coordination.yaml").read_text()
        wf = WorkflowParser.parse(yaml_str)
        assert wf.input_schema is not None
        assert wf.input_schema["type"] == "object"
