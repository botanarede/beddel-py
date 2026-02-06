"""Workflow executor — Async sequential execution with early-return."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from beddel.domain.models import (
    ExecutionContext,
    ExecutionError,
    ExecutionResult,
    PrimitiveError,
    StepResult,
)
from beddel.domain.resolver import VariableResolver

if TYPE_CHECKING:
    from beddel.domain.models import StepDefinition, WorkflowDefinition
    from beddel.domain.ports import ILifecycleHook, ITracer
    from beddel.domain.registry import PrimitiveRegistry

logger = logging.getLogger("beddel.executor")

# Values treated as falsy in condition evaluation
_FALSY_VALUES: frozenset[str] = frozenset({"false", "0", "no", "none", "null", ""})


def _evaluate_condition(value: Any) -> bool:
    """Evaluate a resolved condition value as a boolean.

    Strings are compared case-insensitively against known falsy values.
    All other types use standard Python truthiness.
    """
    if isinstance(value, str):
        return value.strip().lower() not in _FALSY_VALUES
    return bool(value)


class WorkflowExecutor:
    """Orchestrate async sequential execution of workflow steps."""

    def __init__(
        self,
        registry: PrimitiveRegistry,
        resolver: VariableResolver | None = None,
        tracer: ITracer | None = None,
        hooks: list[ILifecycleHook] | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = resolver or VariableResolver()
        self._tracer = tracer
        self._hooks = hooks or []

    async def execute(
        self,
        workflow: WorkflowDefinition,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute a workflow definition sequentially."""
        start = time.monotonic()
        context = ExecutionContext(
            input=input_data or {},
            env=dict(workflow.config.environment),
        )

        for hook in self._hooks:
            await hook.on_workflow_start(workflow, context.input)

        workflow_span = None
        if self._tracer:
            workflow_span = self._tracer.start_workflow_span(workflow)

        step_results: dict[str, StepResult] = {}
        last_output: Any = None

        try:
            for step in workflow.workflow:
                step_result = await self._execute_step(
                    step, context, workflow_span,
                )
                step_results[step.id] = step_result

                if not step_result.success:
                    # Skip strategy: continue workflow despite step failure
                    if step.on_error and step.on_error.strategy == "skip":
                        continue
                    return ExecutionResult(
                        workflow_id=context.workflow_id,
                        success=False,
                        error=step_result.error,
                        step_results=step_results,
                        duration_ms=_elapsed_ms(start),
                    )

                if step.result:
                    context = context.with_step_result(
                        step.result, step_result.output,
                    )
                last_output = step_result.output

            output = self._resolve_output(workflow, context, last_output)

            for hook in self._hooks:
                await hook.on_workflow_end(workflow, output)
            if self._tracer and workflow_span:
                self._tracer.end_span(workflow_span)

            return ExecutionResult(
                workflow_id=context.workflow_id,
                success=True,
                output=output,
                step_results=step_results,
                duration_ms=_elapsed_ms(start),
            )

        except Exception as exc:
            for hook in self._hooks:
                await hook.on_error(exc)
            if self._tracer and workflow_span:
                self._tracer.end_span(workflow_span, error=str(exc))
            raise

    async def execute_step(
        self,
        step: StepDefinition,
        context: ExecutionContext,
    ) -> StepResult:
        """Execute a single step (public API)."""
        return await self._execute_step(step, context, parent_span=None)

    async def _execute_step(
        self,
        step: StepDefinition,
        context: ExecutionContext,
        parent_span: Any,
    ) -> StepResult:
        start = time.monotonic()

        # Condition check
        if step.condition:
            resolved = self._resolver.resolve(step.condition, context)
            if not _evaluate_condition(resolved):
                return StepResult(
                    step_id=step.id, output=None,
                    duration_ms=_elapsed_ms(start),
                )

        for hook in self._hooks:
            await hook.on_step_start(step)

        step_span = None
        if self._tracer:
            step_span = self._tracer.start_step_span(step, parent_span)

        try:
            resolved_config = self._resolver.resolve_dict(
                step.config, context,
            )
            primitive_fn = self._registry.get(step.type)
            output = await primitive_fn(resolved_config, context)

            for hook in self._hooks:
                await hook.on_step_end(step, output)
            if self._tracer and step_span:
                self._tracer.end_span(step_span)

            return StepResult(
                step_id=step.id, output=output,
                success=True, duration_ms=_elapsed_ms(start),
            )

        except (ExecutionError, PrimitiveError) as exc:
            for hook in self._hooks:
                await hook.on_error(exc)
            if self._tracer and step_span:
                self._tracer.end_span(step_span, error=str(exc))
            raise
        except Exception as exc:
            error_msg = f"Step '{step.id}' failed: {exc}"
            logger.error(error_msg)

            for hook in self._hooks:
                await hook.on_error(exc)

            if self._tracer and step_span:
                self._tracer.end_span(step_span, error=error_msg)

            if step.on_error and step.on_error.strategy == "skip":
                logger.info("Step '%s' skipped (on_error=skip)", step.id)
                return StepResult(
                    step_id=step.id, success=False, output=None,
                    error=error_msg, duration_ms=_elapsed_ms(start),
                )

            return StepResult(
                step_id=step.id, success=False,
                error=error_msg, duration_ms=_elapsed_ms(start),
            )

    def _resolve_output(
        self,
        workflow: WorkflowDefinition,
        context: ExecutionContext,
        last_output: Any,
    ) -> Any:
        if workflow.return_template:
            return self._resolver.resolve_dict(
                workflow.return_template, context,
            )
        if workflow.workflow and workflow.workflow[-1].result is None:
            return last_output
        return context.step_results


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000
