"""Goal-oriented execution strategy for Beddel workflows.

Implements a loop-until-outcome pattern that pursues a declared goal
condition adaptively.  The workflow's steps are iterated until the goal
condition evaluates to true or ``max_attempts`` is reached.

Three backoff strategies control the delay between attempts:

- ``fixed``: Constant delay equal to ``backoff_base``.
- ``exponential``: Doubling delay capped at ``backoff_max``.
- ``adaptive``: Delay proportional to iteration progress.

The strategy satisfies :class:`~beddel.domain.ports.IExecutionStrategy`
via structural subtyping (Protocol conformance).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from beddel.domain.errors import ExecutionError
from beddel.domain.models import BackoffType, ExecutionContext, Workflow
from beddel.domain.ports import StepRunner
from beddel.domain.resolver import VariableResolver
from beddel.error_codes import EXEC_GOAL_CONDITION_FAILED, EXEC_GOAL_MAX_ATTEMPTS

_log = logging.getLogger(__name__)


class GoalOrientedStrategy:
    """Execution strategy that loops until a goal condition is met.

    Instead of executing steps once, this strategy runs all workflow steps
    repeatedly until the ``goal_condition`` evaluates to true or
    ``max_attempts`` is exhausted.

    Configuration keys (extracted from constructor ``config``):

    - ``goal_condition`` (str): Required expression evaluated after each
      iteration to determine whether the goal has been met.
    - ``max_attempts`` (int): Maximum loop iterations (default ``10``).
    - ``backoff_type`` (str): One of ``"fixed"``, ``"exponential"``,
      ``"adaptive"`` (default ``"exponential"``).
    - ``backoff_base`` (float): Base delay in seconds (default ``1.0``).
    - ``backoff_max`` (float): Upper bound for delay in seconds
      (default ``30.0``).

    Args:
        config: Optional configuration dict.  ``goal_condition`` is
            required — raises :class:`ValueError` if missing.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the strategy with configuration.

        Args:
            config: Configuration dict.  Supported keys:
                ``goal_condition`` (required), ``max_attempts``,
                ``backoff_type``, ``backoff_base``, ``backoff_max``.

        Raises:
            ValueError: If ``goal_condition`` is missing or
                ``backoff_type`` is not a valid :class:`BackoffType`.
        """
        cfg = config or {}
        goal_condition = cfg.get("goal_condition")
        if not goal_condition:
            raise ValueError("goal_condition is required for GoalOrientedStrategy")
        self._goal_condition: str = goal_condition
        self._max_attempts: int = cfg.get("max_attempts", 10)

        backoff_raw: str = cfg.get("backoff_type", "exponential")
        valid_backoff = {bt.value for bt in BackoffType}
        if backoff_raw not in valid_backoff:
            raise ValueError(
                f"Invalid backoff_type {backoff_raw!r}. Valid values: {sorted(valid_backoff)}"
            )
        self._backoff_type: BackoffType = BackoffType(backoff_raw)
        self._backoff_base: float = cfg.get("backoff_base", 1.0)
        self._backoff_max: float = cfg.get("backoff_max", 30.0)

    async def execute(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        step_runner: StepRunner,
    ) -> None:
        """Run the goal-oriented loop over workflow steps.

        Args:
            workflow: The workflow definition containing steps to execute.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.
            step_runner: :data:`StepRunner` callback that executes a single
                step with full lifecycle handling.

        Raises:
            ExecutionError: With code ``BEDDEL-EXEC-040`` if
                ``max_attempts`` is exhausted without the goal being met.
            ExecutionError: With code ``BEDDEL-EXEC-041`` if the goal
                condition evaluation fails.
        """
        resolver = VariableResolver()
        goal_met = False
        attempt = 0

        for attempt in range(1, self._max_attempts + 1):
            if context.suspended:
                break

            # Run all workflow steps
            for step in workflow.steps:
                await step_runner(step, context)

            # Evaluate goal condition
            try:
                resolved = resolver.resolve(self._goal_condition, context)
            except Exception as exc:
                raise ExecutionError(
                    code=EXEC_GOAL_CONDITION_FAILED,
                    message=(f"Goal condition evaluation failed: {exc}"),
                    details={
                        "goal_condition": self._goal_condition,
                        "attempt": attempt,
                    },
                ) from exc

            # Coerce to bool (same logic as executor's _evaluate_condition)
            if isinstance(resolved, str):
                lower = resolved.lower()
                if lower == "true":
                    goal_met = True
                elif lower == "false":
                    goal_met = False
                else:
                    goal_met = bool(resolved)
            else:
                goal_met = bool(resolved)

            # Fire on_decision lifecycle hook
            decision = "goal_achieved" if goal_met else "goal_retry"
            hooks = context.deps.lifecycle_hooks
            if hooks:
                try:
                    await hooks.on_decision(
                        decision=decision,
                        alternatives=["goal_achieved", "goal_retry"],
                        rationale=(
                            f"Attempt {attempt}/{self._max_attempts}: "
                            f"goal_met={goal_met}, resolved={resolved!r}"
                        ),
                    )
                except Exception:
                    _log.warning("on_decision hook failed", exc_info=True)

            if goal_met:
                break

            # Apply backoff delay (not on last attempt)
            if attempt < self._max_attempts:
                delay = self._calculate_backoff(attempt)
                await asyncio.sleep(delay)

        # Raise if goal never met and not suspended
        if not goal_met and not context.suspended:
            raise ExecutionError(
                code=EXEC_GOAL_MAX_ATTEMPTS,
                message=(
                    f"Goal max attempts exhausted ({self._max_attempts}): "
                    f"goal condition {self._goal_condition!r} never met"
                ),
                details={
                    "goal_condition": self._goal_condition,
                    "max_attempts": self._max_attempts,
                    "attempts": attempt,
                },
            )

        # Store metadata
        context.metadata["_goal"] = {
            "attempts": attempt,
            "goal_met": goal_met,
            "backoff_type": self._backoff_type.value,
        }

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate the backoff delay for the given attempt.

        Args:
            attempt: The current attempt number (1-based).

        Returns:
            The delay in seconds before the next attempt.
        """
        if self._backoff_type == BackoffType.FIXED:
            return self._backoff_base
        if self._backoff_type == BackoffType.EXPONENTIAL:
            return min(self._backoff_base * (2 ** (attempt - 1)), self._backoff_max)
        # ADAPTIVE
        return self._backoff_base * (attempt / self._max_attempts) * self._backoff_max
