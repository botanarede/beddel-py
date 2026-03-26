"""Reflection loop execution strategy for Beddel workflows.

Implements an iterative generate-evaluate loop that runs until convergence
or a maximum iteration count is reached.  Steps tagged ``"generate"`` produce
candidate outputs; steps tagged ``"evaluate"`` score or compare them.

Two convergence algorithms are supported:

- ``exact-match`` (default): converges when the last evaluate result equals
  the previous iteration's result (string comparison).
- ``threshold``: converges when the last evaluate result (cast to float)
  meets or exceeds a configurable threshold.

The strategy satisfies :class:`~beddel.domain.ports.IExecutionStrategy`
via structural subtyping (Protocol conformance).
"""

from __future__ import annotations

import logging
from typing import Any

from beddel.domain.errors import ExecutionError
from beddel.domain.models import ExecutionContext, Workflow
from beddel.domain.ports import StepRunner
from beddel.domain.utils import StepFilter
from beddel.error_codes import (
    EXEC_REFLECTION_NO_EVALUATE,
    EXEC_REFLECTION_NO_GENERATE,
)

_log = logging.getLogger(__name__)


class ReflectionStrategy:
    """Execution strategy that runs an iterative generate-evaluate loop.

    Instead of executing steps sequentially, this strategy partitions
    workflow steps by tag (``"generate"`` and ``"evaluate"``) and runs
    them in a loop until convergence or ``max_iterations`` is reached.

    Configuration keys (extracted from constructor ``config``):

    - ``max_iterations`` (int): Maximum loop iterations (default ``5``).
    - ``convergence_algorithm`` (str): ``"exact-match"`` or ``"threshold"``
      (default ``"exact-match"``).
    - ``convergence_threshold`` (float): Threshold value for the
      ``"threshold"`` algorithm (default ``0.9``).

    Args:
        config: Optional configuration dict.  Missing keys use defaults.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the strategy with optional configuration.

        Args:
            config: Optional configuration dict.  Supported keys:
                ``max_iterations``, ``convergence_algorithm``,
                ``convergence_threshold``.
        """
        cfg = config or {}
        self._max_iterations: int = cfg.get("max_iterations", 5)
        self._algorithm: str = cfg.get("convergence_algorithm", "exact-match")
        self._threshold: float = cfg.get("convergence_threshold", 0.9)

    async def execute(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        step_runner: StepRunner,
    ) -> None:
        """Run the reflection loop over generate and evaluate steps.

        Args:
            workflow: The workflow definition containing tagged steps.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.
            step_runner: :data:`StepRunner` callback that executes a single
                step with full lifecycle handling.

        Raises:
            ExecutionError: With code ``BEDDEL-EXEC-020`` if no steps
                tagged ``"generate"`` are found.
            ExecutionError: With code ``BEDDEL-EXEC-021`` if no steps
                tagged ``"evaluate"`` are found.
        """
        # 1. Partition steps by tag (pre-computed once)
        gen_pred = StepFilter.filter_by_tag(["generate"])
        eval_pred = StepFilter.filter_by_tag(["evaluate"])
        generate_steps = [s for s in workflow.steps if gen_pred(s)]
        evaluate_steps = [s for s in workflow.steps if eval_pred(s)]

        if not generate_steps:
            raise ExecutionError(
                EXEC_REFLECTION_NO_GENERATE,
                "No steps tagged 'generate' found in workflow",
            )
        if not evaluate_steps:
            raise ExecutionError(
                EXEC_REFLECTION_NO_EVALUATE,
                "No steps tagged 'evaluate' found in workflow",
            )

        # 2. Reflection loop
        previous_eval: Any = None
        converged = False
        iteration = 0

        for iteration in range(1, self._max_iterations + 1):  # noqa: B007
            if context.suspended:
                break

            # Run generate steps
            for step in generate_steps:
                await step_runner(step, context)

            # Check suspended after generate (before evaluate)
            if context.suspended:
                break

            # Run evaluate steps
            for step in evaluate_steps:
                await step_runner(step, context)

            # Get last evaluate result
            current_eval = context.step_results[evaluate_steps[-1].id]

            # Check convergence
            if self._algorithm == "threshold":
                converged = float(current_eval) >= self._threshold
            else:
                # exact-match: first iteration previous is None → never converges
                converged = str(current_eval) == str(previous_eval)

            if converged:
                break

            # Inject feedback for next iteration
            context.step_results["_reflection_feedback"] = current_eval
            previous_eval = current_eval

        # 3. Store reflection metadata
        context.metadata["_reflection"] = {
            "iterations": iteration,
            "converged": converged,
            "algorithm": self._algorithm,
        }
