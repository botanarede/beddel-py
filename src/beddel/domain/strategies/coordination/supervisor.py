"""Supervisor coordination strategy for multi-agent workflows.

A central supervisor agent receives the task, decomposes it into subtasks
assigned to named specialist agents, dispatches each subtask, collects
results, and synthesizes a final output.

Only stdlib + domain core imports are allowed (hexagonal architecture rule).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from beddel.domain.errors import CoordinationError
from beddel.domain.models import (
    AgentResult,
    CoordinationResult,
    CoordinationTask,
    ExecutionContext,
)
from beddel.domain.ports import IAgentAdapter
from beddel.error_codes import (
    COORD_NO_AGENTS,
    COORD_STRATEGY_FAILED,
    COORD_SUPERVISOR_FAILED,
)

_log = logging.getLogger(__name__)


class SupervisorStrategy:
    """Coordination strategy where a supervisor agent orchestrates specialists.

    The supervisor agent (either the agent keyed ``"supervisor"`` or the
    first agent in the dict) performs three phases:

    1. **Decompose** — receives a structured prompt and returns a JSON
       mapping of ``{agent_name: subtask_prompt}`` pairs.
    2. **Dispatch** — each subtask is sent to the named specialist agent
       via :meth:`IAgentAdapter.execute`.
    3. **Synthesize** — the supervisor is called again with all agent
       results to produce the final combined output.

    Satisfies :class:`~beddel.domain.ports.ICoordinationStrategy` via
    structural subtyping (Protocol conformance).
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config: dict[str, Any] = config or {}

    async def coordinate(
        self,
        agents: dict[str, IAgentAdapter],
        task: CoordinationTask,
        context: ExecutionContext,
    ) -> CoordinationResult:
        """Coordinate work via supervisor decomposition, dispatch, and synthesis.

        Args:
            agents: Named agent adapters available for coordination.
            task: The coordination task describing the work to distribute.
            context: The current workflow execution context.

        Returns:
            A :class:`CoordinationResult` with synthesized output and
            per-agent results.

        Raises:
            CoordinationError: With ``COORD_NO_AGENTS`` if agents dict is
                empty, ``COORD_SUPERVISOR_FAILED`` if decomposition fails,
                or ``COORD_STRATEGY_FAILED`` for general failures.
        """
        if not agents:
            raise CoordinationError(
                COORD_NO_AGENTS,
                "No agents configured for supervisor coordination",
            )

        try:
            supervisor = self._resolve_supervisor(agents)

            # Phase 1: Decompose
            assignments = await self._decompose(supervisor, agents, task)

            # Phase 2: Dispatch
            agent_results = await self._dispatch(agents, assignments)

            # Phase 3: Synthesize
            output = await self._synthesize(supervisor, task, agent_results)

            return CoordinationResult(
                output=output,
                agent_results=agent_results,
                strategy_name="supervisor",
                metadata={
                    "assignments": {k: v for k, v in assignments.items()},
                    "agents_used": list(agent_results.keys()),
                },
            )
        except CoordinationError:
            raise
        except Exception as exc:
            raise CoordinationError(
                COORD_STRATEGY_FAILED,
                f"Supervisor coordination failed: {exc}",
                details={"original_error": str(exc)},
            ) from exc

    def _resolve_supervisor(self, agents: dict[str, IAgentAdapter]) -> IAgentAdapter:
        """Select the supervisor agent from the agents dict.

        Uses the ``"supervisor"`` key if present, otherwise the first agent.
        """
        if "supervisor" in agents:
            return agents["supervisor"]
        return next(iter(agents.values()))

    async def _decompose(
        self,
        supervisor: IAgentAdapter,
        agents: dict[str, IAgentAdapter],
        task: CoordinationTask,
    ) -> dict[str, str]:
        """Ask the supervisor to decompose the task into agent assignments.

        Returns:
            Mapping of ``{agent_name: subtask_prompt}``.

        Raises:
            CoordinationError: If decomposition output cannot be parsed.
        """
        agent_names = list(agents.keys())
        prompt = (
            "You are a supervisor agent. Decompose the following task into "
            "subtasks and assign each to one of the available agents.\n\n"
            f"Available agents: {agent_names}\n\n"
            f"Task: {task.prompt}\n\n"
            "Respond with JSON only, in this exact format:\n"
            '{"assignments": [{"agent": "<agent_name>", "task": "<subtask_prompt>"}, ...]}'
        )

        result = await supervisor.execute(prompt)
        return self._parse_assignments(result.output)

    def _parse_assignments(self, output: str) -> dict[str, str]:
        """Parse supervisor output into agent-to-subtask mapping.

        Tries JSON parsing first, then falls back to line-based parsing.

        Raises:
            CoordinationError: If no assignments can be extracted.
        """
        # Try JSON parsing
        try:
            data = json.loads(output)
            if isinstance(data, dict) and "assignments" in data:
                assignments: dict[str, str] = {}
                for item in data["assignments"]:
                    agent = item.get("agent", "")
                    subtask = item.get("task", "")
                    if agent and subtask:
                        assignments[agent] = subtask
                if assignments:
                    return assignments
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

        # Try extracting JSON from within the output (e.g. markdown fences)
        try:
            start = output.index("{")
            end = output.rindex("}") + 1
            data = json.loads(output[start:end])
            if isinstance(data, dict) and "assignments" in data:
                assignments = {}
                for item in data["assignments"]:
                    agent = item.get("agent", "")
                    subtask = item.get("task", "")
                    if agent and subtask:
                        assignments[agent] = subtask
                if assignments:
                    return assignments
        except (ValueError, json.JSONDecodeError, TypeError, KeyError):
            pass

        raise CoordinationError(
            COORD_SUPERVISOR_FAILED,
            "Failed to parse supervisor decomposition output",
            details={"raw_output": output[:500]},
        )

    async def _dispatch(
        self,
        agents: dict[str, IAgentAdapter],
        assignments: dict[str, str],
    ) -> dict[str, AgentResult]:
        """Dispatch subtasks to named agents and collect results.

        Agents not found in the dict are skipped with a warning (the whole
        coordination is not failed).
        """
        results: dict[str, AgentResult] = {}
        for agent_name, subtask_prompt in assignments.items():
            if agent_name not in agents:
                _log.warning(
                    "Agent '%s' not found in agents dict, skipping",
                    agent_name,
                )
                continue
            result = await agents[agent_name].execute(subtask_prompt)
            results[agent_name] = result
        return results

    async def _synthesize(
        self,
        supervisor: IAgentAdapter,
        task: CoordinationTask,
        agent_results: dict[str, AgentResult],
    ) -> str:
        """Ask the supervisor to synthesize a final output from all results.

        Returns:
            The synthesized output string.
        """
        results_text = "\n\n".join(
            f"Agent '{name}' result:\n{result.output}" for name, result in agent_results.items()
        )
        prompt = (
            "You are a supervisor agent. Synthesize the following agent "
            "results into a single coherent response.\n\n"
            f"Original task: {task.prompt}\n\n"
            f"Agent results:\n{results_text}\n\n"
            "Provide a synthesized final answer."
        )
        result = await supervisor.execute(prompt)
        return result.output
