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
from beddel.domain.models import (
    ErrorSemantics,
    ExecutionContext,
    ParallelConfig,
    Step,
    Workflow,
)
from beddel.domain.ports import StepRunner
from beddel.error_codes import EXEC_PARALLEL_COLLECT_FAILED, EXEC_PARALLEL_GROUP_FAILED

_log = logging.getLogger(__name__)


class ParallelExecutionStrategy:
    """Execution strategy that runs parallel step groups via asyncio.gather.

    Steps with ``parallel=True`` are grouped into parallel blocks that
    execute concurrently.  Steps with ``parallel=False`` (default) execute
    sequentially.  Groups are processed in declaration order.

    Configuration is parsed into :class:`ParallelConfig`:

    - ``concurrency_limit`` (int): Max concurrent steps (default: 5).
      Set to 0 for unbounded concurrency.
    - ``error_semantics`` (str): ``"fail-fast"`` or ``"collect-all"``
      (default: ``"fail-fast"``).
    - ``isolate_context`` (bool): When ``True``, each parallel branch
      receives a shallow-cloned context so branches have independent
      ``step_results`` and ``metadata``.  Results are merged back to the
      parent after all branches complete (default: ``False``).

    Args:
        config: Optional configuration dict parsed into ParallelConfig.

    Raises:
        ValueError: If ``concurrency_limit`` is negative or
            ``error_semantics`` is not a valid enum value.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the strategy with optional configuration.

        Args:
            config: Optional configuration dict.  Parsed into
                :class:`ParallelConfig`.  When ``None``, defaults apply.

        Raises:
            ValueError: If ``concurrency_limit`` is negative or
                ``error_semantics`` is not a valid enum value.
        """
        self._config = config or {}
        try:
            self._parallel_config: ParallelConfig = (
                ParallelConfig(**config) if config else ParallelConfig()
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        if self._parallel_config.concurrency_limit < 0:
            msg = "concurrency_limit must be >= 0"
            raise ValueError(msg)

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
                group execution fails (fail-fast mode).
            ExecutionError: With code ``BEDDEL-EXEC-031`` if one or more
                steps fail (collect-all mode).
        """
        groups = self._group_steps(workflow.steps)

        for is_parallel, steps in groups:
            if context.suspended:
                break

            if not is_parallel:
                await step_runner(steps[0], context)
            else:
                await self._run_parallel_group(steps, context, step_runner)

    async def _run_parallel_group(
        self,
        steps: list[Step],
        context: ExecutionContext,
        step_runner: StepRunner,
    ) -> None:
        """Execute a parallel group with concurrency limits and error semantics.

        Args:
            steps: The parallel steps to execute concurrently.
            context: Mutable runtime context.
            step_runner: Callback that executes a single step.
        """
        limit = self._parallel_config.concurrency_limit
        semaphore: asyncio.Semaphore | None = asyncio.Semaphore(limit) if limit > 0 else None
        isolate = self._parallel_config.isolate_context

        # Create per-branch contexts if isolation is enabled
        branch_contexts: list[ExecutionContext] = []
        if isolate:
            branch_contexts = [self._clone_context(context) for _ in steps]

        async def limited_runner(step: Step, ctx: ExecutionContext) -> Any:
            if semaphore is not None:
                async with semaphore:
                    return await step_runner(step, ctx)
            return await step_runner(step, ctx)

        try:
            if self._parallel_config.error_semantics == ErrorSemantics.FAIL_FAST:
                await self._run_fail_fast(
                    steps,
                    branch_contexts if isolate else [context] * len(steps),
                    limited_runner,
                )
            else:
                await self._run_collect_all(
                    steps,
                    branch_contexts if isolate else [context] * len(steps),
                    limited_runner,
                )
        finally:
            # Merge step_results from branch contexts back to parent
            if isolate:
                for bc in branch_contexts:
                    for step_id, result in bc.step_results.items():
                        if step_id not in context.step_results:
                            context.step_results[step_id] = result

    async def _run_fail_fast(
        self,
        steps: list[Step],
        contexts: list[ExecutionContext],
        runner: Any,
    ) -> None:
        """Fail-fast: cancel siblings on first error."""
        tasks = [
            asyncio.create_task(runner(s, ctx)) for s, ctx in zip(steps, contexts, strict=True)
        ]
        try:
            await asyncio.gather(*tasks)
        except Exception as exc:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise ExecutionError(
                EXEC_PARALLEL_GROUP_FAILED,
                f"Parallel group execution failed: {exc}",
                details={
                    "original_error": str(exc),
                    "error_type": type(exc).__name__,
                    "step_ids": [s.id for s in steps],
                },
            ) from exc

    async def _run_collect_all(
        self,
        steps: list[Step],
        contexts: list[ExecutionContext],
        runner: Any,
    ) -> None:
        """Collect-all: run all steps, aggregate errors."""
        results = await asyncio.gather(
            *[runner(s, ctx) for s, ctx in zip(steps, contexts, strict=True)],
            return_exceptions=True,
        )
        errors: list[dict[str, str]] = []
        for step, ctx, result in zip(steps, contexts, results, strict=True):
            if isinstance(result, Exception):
                errors.append(
                    {
                        "step_id": step.id,
                        "error": str(result),
                        "error_type": type(result).__name__,
                    }
                )
            else:
                ctx.step_results[step.id] = result
        if errors:
            raise ExecutionError(
                EXEC_PARALLEL_COLLECT_FAILED,
                f"Parallel group had {len(errors)} error(s)",
                details={"errors": errors},
            )

    @staticmethod
    def _clone_context(context: ExecutionContext) -> ExecutionContext:
        """Create a shallow clone of the execution context for branch isolation.

        Shares ``workflow_id``, ``inputs`` (read-only by convention), and
        ``deps`` (singleton services).  Copies ``step_results`` and
        ``metadata`` dicts so branches have independent state.

        Args:
            context: The parent execution context to clone.

        Returns:
            A new ExecutionContext with independent step_results and metadata.
        """
        return ExecutionContext(
            workflow_id=context.workflow_id,
            inputs=context.inputs,
            step_results=dict(context.step_results),
            metadata=dict(context.metadata),
            current_step_id=context.current_step_id,
            deps=context.deps,
        )

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
                    if current_group:
                        groups.append((False, current_group))
                        current_group = []
                    in_parallel = True
                current_group.append(step)
            else:
                if in_parallel:
                    if current_group:
                        groups.append((True, current_group))
                        current_group = []
                    in_parallel = False
                groups.append((False, [step]))

        if current_group and in_parallel:
            groups.append((True, current_group))

        return groups
