"""Handoff coordination strategy for multi-agent workflows.

Implements agent-to-agent transfer with context passing, inspired by the
OpenAI Agents SDK handoff primitive.  Each agent can produce a
``__handoff__:{agent_name}`` marker in its output to transfer control to
the next agent with accumulated context.

Only stdlib + domain core imports are allowed (hexagonal architecture rule).
"""

from __future__ import annotations

import logging
import re
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
    COORD_HANDOFF_FAILED,
    COORD_NO_AGENTS,
    COORD_STRATEGY_FAILED,
)

_log = logging.getLogger(__name__)

_HANDOFF_RE = re.compile(r"__handoff__:(\S+)")


class HandoffStrategy:
    """Coordination strategy where agents hand off control to one another.

    The first agent executes with the task prompt.  If its output contains
    the marker ``__handoff__:{agent_name}``, the strategy strips the marker,
    records the output, and passes accumulated context to the named agent.
    The chain continues until an agent produces output without a handoff
    marker or the configurable ``max_handoffs`` limit is reached.

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
        """Run the handoff chain until completion or max handoffs.

        Args:
            agents: Named agent adapters available for coordination.
            task: The coordination task describing the work.
            context: The current workflow execution context.

        Returns:
            A :class:`CoordinationResult` with the final agent's output
            and metadata about the handoff chain.

        Raises:
            CoordinationError: With ``COORD_NO_AGENTS`` if agents dict is
                empty, ``COORD_HANDOFF_FAILED`` if max handoffs exceeded
                or a handoff targets an unknown agent, or
                ``COORD_STRATEGY_FAILED`` for general failures.
        """
        if not agents:
            raise CoordinationError(
                COORD_NO_AGENTS,
                "No agents configured for handoff coordination",
            )

        max_handoffs: int = int(self._config.get("max_handoffs", 5))

        try:
            return await self._run_chain(agents, task, max_handoffs)
        except CoordinationError:
            raise
        except Exception as exc:
            raise CoordinationError(
                COORD_STRATEGY_FAILED,
                f"Handoff coordination failed: {exc}",
                details={"original_error": str(exc)},
            ) from exc

    async def _run_chain(
        self,
        agents: dict[str, IAgentAdapter],
        task: CoordinationTask,
        max_handoffs: int,
    ) -> CoordinationResult:
        """Execute the handoff chain, accumulating context at each step."""
        current_agent_name = self._resolve_first_agent(task, agents)
        history: list[dict[str, str]] = []
        agent_results: dict[str, AgentResult] = {}
        chain: list[str] = []
        handoff_count = 0

        while True:
            if current_agent_name not in agents:
                raise CoordinationError(
                    COORD_HANDOFF_FAILED,
                    f"Handoff target agent '{current_agent_name}' not found",
                    details={"available_agents": list(agents.keys())},
                )

            prompt = self._build_prompt(task.prompt, history)
            result = await agents[current_agent_name].execute(prompt)
            chain.append(current_agent_name)
            agent_results[current_agent_name] = result

            match = _HANDOFF_RE.search(result.output)
            if match is None:
                # No handoff — chain ends here
                return CoordinationResult(
                    output=result.output,
                    agent_results=agent_results,
                    strategy_name="handoff",
                    metadata={
                        "chain": chain,
                        "handoff_count": handoff_count,
                    },
                )

            # Strip the handoff marker from the output before accumulating
            next_agent = match.group(1)
            clean_output = _HANDOFF_RE.sub("", result.output).strip()
            history.append({"agent": current_agent_name, "output": clean_output})

            handoff_count += 1
            if handoff_count > max_handoffs:
                raise CoordinationError(
                    COORD_HANDOFF_FAILED,
                    f"Max handoffs ({max_handoffs}) exceeded",
                    details={"chain": chain, "handoff_count": handoff_count},
                )

            _log.debug(
                "Handoff %d: %s → %s",
                handoff_count,
                current_agent_name,
                next_agent,
            )
            current_agent_name = next_agent

    @staticmethod
    def _resolve_first_agent(
        task: CoordinationTask,
        agents: dict[str, IAgentAdapter],
    ) -> str:
        """Determine the first agent to execute.

        Uses the first entry in ``task.subtasks`` if provided, otherwise
        the first key in the agents dict.
        """
        if task.subtasks:
            return task.subtasks[0]
        return next(iter(agents))

    @staticmethod
    def _build_prompt(
        original_prompt: str,
        history: list[dict[str, str]],
    ) -> str:
        """Build the prompt for the next agent in the chain.

        Combines the original prompt with accumulated outputs from all
        previous agents.
        """
        if not history:
            return original_prompt

        context_parts = [f"[{entry['agent']}]: {entry['output']}" for entry in history]
        return original_prompt + "\n\nPrevious agent outputs:\n" + "\n".join(context_parts)
