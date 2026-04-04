"""Parallel dispatch coordination strategy for multi-agent workflows.

Fan-out a single task prompt to all agents concurrently and aggregate
results using a configurable mode: ``merge``, ``first``, or ``vote``.

Only stdlib + domain core imports are allowed (hexagonal architecture rule).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
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
    COORD_PARALLEL_FAILED,
    COORD_STRATEGY_FAILED,
)

_log = logging.getLogger(__name__)


class ParallelDispatchStrategy:
    """Coordination strategy that fans out a prompt to all agents in parallel.

    All agents receive the same task prompt concurrently via
    ``asyncio.gather``.  Results are aggregated according to the
    configured mode:

    - **merge** (default): concatenate all agent outputs with name headers.
    - **first**: return the first successful result, cancel the rest.
    - **vote**: simple majority — most common output string wins.

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
        """Fan-out the task prompt to all agents and aggregate results.

        Args:
            agents: Named agent adapters available for coordination.
            task: The coordination task describing the work.
            context: The current workflow execution context.

        Returns:
            A :class:`CoordinationResult` with aggregated output and
            per-agent results.

        Raises:
            CoordinationError: With ``COORD_NO_AGENTS`` if agents dict is
                empty, ``COORD_PARALLEL_FAILED`` if all agents fail, or
                ``COORD_STRATEGY_FAILED`` for general failures.
        """
        if not agents:
            raise CoordinationError(
                COORD_NO_AGENTS,
                "No agents configured for parallel dispatch coordination",
            )

        mode: str = str(self._config.get("aggregation", "merge"))

        try:
            if mode == "first":
                return await self._run_first(agents, task)
            if mode == "vote":
                return await self._run_vote(agents, task)
            return await self._run_merge(agents, task)
        except CoordinationError:
            raise
        except Exception as exc:
            raise CoordinationError(
                COORD_STRATEGY_FAILED,
                f"Parallel dispatch coordination failed: {exc}",
                details={"original_error": str(exc)},
            ) from exc

    # ── Merge mode ────────────────────────────────────────────────────

    async def _run_merge(
        self,
        agents: dict[str, IAgentAdapter],
        task: CoordinationTask,
    ) -> CoordinationResult:
        """Execute all agents and merge outputs with name headers."""
        names = list(agents.keys())
        results = await asyncio.gather(
            *[self._safe_execute(agents[n], task.prompt) for n in names],
        )

        successes: dict[str, AgentResult] = {}
        parts: list[str] = []
        succeeded = 0
        failed = 0

        for name, outcome in zip(names, results, strict=True):
            if isinstance(outcome, Exception):
                failed += 1
                parts.append(f"[{name}]: ERROR — {outcome}")
            else:
                succeeded += 1
                successes[name] = outcome
                parts.append(f"[{name}]:\n{outcome.output}")

        if succeeded == 0:
            raise CoordinationError(
                COORD_PARALLEL_FAILED,
                "All agents failed in parallel dispatch (merge mode)",
                details={"agents": names},
            )

        output = "\n\n".join(parts)
        return CoordinationResult(
            output=output,
            agent_results=successes,
            strategy_name="parallel-dispatch",
            metadata={
                "aggregation": "merge",
                "agents_succeeded": succeeded,
                "agents_failed": failed,
            },
        )

    # ── First mode ────────────────────────────────────────────────────

    async def _run_first(
        self,
        agents: dict[str, IAgentAdapter],
        task: CoordinationTask,
    ) -> CoordinationResult:
        """Return the first successful result, cancel remaining tasks."""
        names = list(agents.keys())
        pending: set[asyncio.Task[AgentResult]] = set()
        name_by_task: dict[asyncio.Task[AgentResult], str] = {}

        for name in names:
            t = asyncio.create_task(agents[name].execute(task.prompt))
            pending.add(t)
            name_by_task[t] = name

        succeeded = 0
        failed = 0
        first_result: AgentResult | None = None
        first_name: str = ""

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                exc = t.exception()
                if exc is not None:
                    failed += 1
                    _log.debug(
                        "Agent '%s' failed: %s",
                        name_by_task[t],
                        exc,
                    )
                    continue
                # First success — cancel remaining and return
                first_result = t.result()
                first_name = name_by_task[t]
                succeeded = 1
                for p in pending:
                    p.cancel()
                # Drain cancelled tasks to avoid warnings
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                pending = set()
                break

            if first_result is not None:
                break

        if first_result is None:
            raise CoordinationError(
                COORD_PARALLEL_FAILED,
                "All agents failed in parallel dispatch (first mode)",
                details={"agents": names},
            )

        return CoordinationResult(
            output=first_result.output,
            agent_results={first_name: first_result},
            strategy_name="parallel-dispatch",
            metadata={
                "aggregation": "first",
                "agents_succeeded": succeeded,
                "agents_failed": failed,
            },
        )

    # ── Vote mode ─────────────────────────────────────────────────────

    async def _run_vote(
        self,
        agents: dict[str, IAgentAdapter],
        task: CoordinationTask,
    ) -> CoordinationResult:
        """Collect all outputs and return the majority vote winner."""
        names = list(agents.keys())
        results = await asyncio.gather(
            *[self._safe_execute(agents[n], task.prompt) for n in names],
        )

        successes: dict[str, AgentResult] = {}
        outputs: list[str] = []
        succeeded = 0
        failed = 0

        for name, outcome in zip(names, results, strict=True):
            if isinstance(outcome, Exception):
                failed += 1
            else:
                succeeded += 1
                successes[name] = outcome
                outputs.append(outcome.output)

        if succeeded == 0:
            raise CoordinationError(
                COORD_PARALLEL_FAILED,
                "All agents failed in parallel dispatch (vote mode)",
                details={"agents": names},
            )

        # Simple majority — most common output wins; tie → first in list
        counts = Counter(outputs)
        winner = counts.most_common(1)[0][0]

        return CoordinationResult(
            output=winner,
            agent_results=successes,
            strategy_name="parallel-dispatch",
            metadata={
                "aggregation": "vote",
                "agents_succeeded": succeeded,
                "agents_failed": failed,
            },
        )

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    async def _safe_execute(
        agent: IAgentAdapter,
        prompt: str,
    ) -> AgentResult | Exception:
        """Execute an agent, returning the exception on failure."""
        try:
            return await agent.execute(prompt)
        except Exception as exc:  # noqa: BLE001
            return exc
