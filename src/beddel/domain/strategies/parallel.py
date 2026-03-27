"""Parallel execution strategy for Beddel workflows.

Partitions workflow steps into sequential and parallel groups based on
the ``Step.parallel`` field.  Sequential groups execute one step at a time;
parallel groups launch all steps concurrently via ``asyncio.gather``.

The strategy satisfies :class:`~beddel.domain.ports.IExecutionStrategy`
via structural subtyping (Protocol conformance).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from beddel.domain.errors import ExecutionError
from beddel.domain.models import ExecutionContext, Step, Workflow
from beddel.domain.ports import StepRunner
from beddel.error_codes import EXEC_PARALLEL_GROUP_FAILED

_log = logging.getLogger(__name__)


class ParallelExecutionStrategy:
    """Execution strategy that runs parallel step groups via asyncio.gather.

    Steps with ``parallel=True`` are grouped into parallel blocks that
    execute concurrently.  Steps with ``parallel=False`` (default) execute
    sequentially.  Groups are processed in declaration order.

    Configuration keys (reserved for Story 4.2b):

    - ``concurrency_limit`` (int): Max concurrent steps (default: unlimited).
    - ``error_semantics`` (str): ``"fail-fast"`` or ``"collect-all"``
      (default: ``"fail-fast"``).

    Args:
        config: Optional configuration dict.  Reserved for Story 4.2b.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the strategy with optional configuration.

        Args:
            config: Optional configuration dict.  Reserved for Story 4.2b
                (concurrency limits, error semantics).
        """
        self._config = config or {}

    async def execute(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        step_runner: StepRunner,
    ) -> None:
        """Execute workflow steps, running parallel groups concurrently.

        Args:
            workflow: The workflow definition containing steps.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.
            step_runner: :data:`StepRunner` callback that executes a single
                step with full lifecycle handling.

        Raises:
            ExecutionError: With code ``BEDDEL-EXEC-030`` if a parallel
                group execution fails.
        """
        groups = self._group_steps(workflow.steps)

        for is_parallel, steps in groups:
            if context.suspended:
                break

            if not is_parallel:
                # Sequential: single step
                await step_runner(steps[0], context)
            else:
                # Parallel: fan-out via asyncio.gather
                try:
                    await asyncio.gather(*[step_runner(s, context) for s in steps])
                except Exception as exc:
                    raise ExecutionError(
                        EXEC_PARALLEL_GROUP_FAILED,
                        f"Parallel group execution failed: {exc}",
                        details={
                            "original_error": str(exc),
                            "step_ids": [s.id for s in steps],
                        },
                    ) from exc

    @staticmethod
    def _group_steps(
        steps: list[Step],
    ) -> list[tuple[bool, list[Step]]]:
        """Partition steps into sequential and parallel groups.

        Consecutive steps with ``parallel=True`` form a parallel group.
        Steps with ``parallel=False`` form single-step sequential groups.

        Args:
            steps: The workflow steps in declaration order.

        Returns:
            Ordered list of ``(is_parallel, steps)`` tuples.
        """
        if not steps:
            return []

        groups: list[tuple[bool, list[Step]]] = []
        current_group: list[Step] = []
        in_parallel = False

        for step in steps:
            if step.parallel:
                if not in_parallel:
                    # Flush any pending sequential step
                    if current_group:
                        groups.append((False, current_group))
                        current_group = []
                    in_parallel = True
                current_group.append(step)
            else:
                if in_parallel:
                    # Flush the parallel group
                    if current_group:
                        groups.append((True, current_group))
                        current_group = []
                    in_parallel = False
                # Each sequential step is its own group
                groups.append((False, [step]))

        # Flush remaining parallel group
        if current_group and in_parallel:
            groups.append((True, current_group))

        return groups
