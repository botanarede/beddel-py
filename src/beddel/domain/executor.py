"""Workflow executor for the Beddel SDK.

Orchestrates sequential execution of workflow steps, resolving variable
references, dispatching lifecycle hooks, and collecting results into an
:class:`~beddel.domain.models.ExecutionContext`.

Only stdlib + pydantic + domain imports are allowed in this module
(domain core rule).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.errors import ExecutionError
from beddel.domain.models import (
    BeddelEvent,
    EventType,
    ExecutionContext,
    RetryConfig,
    Step,
    StrategyType,
    Workflow,
)
from beddel.domain.ports import IExecutionStrategy, ILifecycleHook, ILLMProvider, IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.domain.resolver import VariableResolver

__all__ = [
    "SequentialStrategy",
    "WorkflowExecutor",
]

logger = logging.getLogger(__name__)


class SequentialStrategy:
    """Execute workflow steps sequentially in declaration order.

    This is the default execution strategy used by
    :class:`WorkflowExecutor`.  It iterates ``workflow.steps`` and calls
    the ``step_runner`` callback for each step in order.

    The ``step_runner`` callback handles all per-step concerns (condition
    evaluation, timeout, error strategies, lifecycle hooks) — this
    strategy only controls iteration order.

    [Source: docs/architecture/6-port-interfaces.md#65-iexecutionstrategy]
    """

    async def execute(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        step_runner: Any,
    ) -> None:
        """Execute steps sequentially in declaration order.

        Args:
            workflow: The workflow definition containing steps to execute.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.
            step_runner: Async callback ``(step, context) -> Any`` that
                executes a single step with full lifecycle handling.
        """
        for step in workflow.steps:
            if context.suspended:
                break
            await step_runner(step, context)


class WorkflowExecutor:
    """Executes a :class:`Workflow` by running its steps sequentially.

    The executor resolves variable references in step configs, looks up
    primitives from the registry, and threads an
    :class:`ExecutionContext` through the entire run.  Optional lifecycle
    hooks receive notifications at key execution points.

    Args:
        registry: Primitive registry used to look up step primitives.
        provider: Optional LLM provider injected into
            ``context.metadata["llm_provider"]``.
        hooks: Optional lifecycle hooks injected into
            ``context.metadata["lifecycle_hooks"]`` and called during
            execution.
        strategy: Optional execution strategy controlling how workflow
            steps are iterated.  Defaults to :class:`SequentialStrategy`
            when ``None``.

    Example::

        executor = WorkflowExecutor(registry, provider=my_llm)
        result = await executor.execute(workflow, {"topic": "AI"})
    """

    def __init__(
        self,
        registry: PrimitiveRegistry,
        provider: ILLMProvider | None = None,
        hooks: list[ILifecycleHook] | None = None,
        strategy: IExecutionStrategy | None = None,
    ) -> None:
        self._registry = registry
        self._provider = provider
        self._hooks: list[ILifecycleHook] = hooks or []
        self._resolver = VariableResolver()
        self._strategy: IExecutionStrategy = strategy or SequentialStrategy()

    async def execute(
        self,
        workflow: Workflow,
        inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow sequentially, returning collected results.

        Creates an :class:`ExecutionContext`, injects the LLM provider and
        lifecycle hooks into metadata, iterates steps in order, and returns
        the accumulated step results and metadata.

        Args:
            workflow: The workflow definition to execute.
            inputs: Optional input dict available as ``$input.*`` in step
                configs.

        Returns:
            A dict with ``"step_results"`` mapping step ids to their return
            values and ``"metadata"`` carrying runtime metadata.

        Raises:
            ExecutionError: ``BEDDEL-EXEC-002`` when a step fails during
                execution.
        """
        effective_inputs = inputs or {}
        context = ExecutionContext(
            workflow_id=workflow.id,
            inputs=effective_inputs,
        )

        if self._provider is not None:
            context.metadata["llm_provider"] = self._provider
        context.metadata["lifecycle_hooks"] = self._hooks

        await self._dispatch_hook("on_workflow_start", workflow.id, effective_inputs)

        await self._strategy.execute(workflow, context, self._execute_step)

        result: dict[str, Any] = {
            "step_results": dict(context.step_results),
            "metadata": dict(context.metadata),
        }

        await self._dispatch_hook("on_workflow_end", workflow.id, result)
        return result

    async def execute_stream(
        self,
        workflow: Workflow,
        inputs: dict[str, Any] | None = None,
    ) -> AsyncGenerator[BeddelEvent, None]:
        """Stream workflow execution as a sequence of events.

        Mirrors the logic of :meth:`execute` but yields
        :class:`~beddel.domain.models.BeddelEvent` instances at each
        lifecycle point instead of collecting results into a dict.

        A temporary :class:`ILifecycleHook` is installed to capture events
        produced by the existing execution internals (``_execute_step``,
        ``_retry_step``, etc.).  After each internal call the captured
        events are yielded and the buffer is cleared, giving the caller
        incremental visibility into the run.

        For steps with ``stream=True``, the stored async-generator result
        is consumed and each chunk is yielded as a ``TEXT_CHUNK`` event.

        Args:
            workflow: The workflow definition to execute.
            inputs: Optional input dict available as ``$input.*`` in step
                configs.

        Yields:
            :class:`BeddelEvent` instances for workflow start/end, step
            start/end, errors, retries, and text chunks.
        """
        events: list[BeddelEvent] = []

        class _Collector(ILifecycleHook):
            """Internal hook that buffers events for the generator."""

            async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
                events.append(
                    BeddelEvent(
                        event_type=EventType.WORKFLOW_START,
                        data={"workflow_id": workflow_id, "inputs": inputs},
                    )
                )

            async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
                events.append(
                    BeddelEvent(
                        event_type=EventType.WORKFLOW_END,
                        data={"workflow_id": workflow_id},
                    )
                )

            async def on_step_start(self, step_id: str, primitive: str) -> None:
                events.append(
                    BeddelEvent(
                        event_type=EventType.STEP_START,
                        step_id=step_id,
                        data={"primitive": primitive},
                    )
                )

            async def on_step_end(self, step_id: str, result: Any) -> None:
                events.append(
                    BeddelEvent(
                        event_type=EventType.STEP_END,
                        step_id=step_id,
                        data={"result": result},
                    )
                )

            async def on_error(self, step_id: str, error: Exception) -> None:
                events.append(
                    BeddelEvent(
                        event_type=EventType.ERROR,
                        step_id=step_id,
                        data={
                            "error": str(error),
                            "error_type": type(error).__name__,
                        },
                    )
                )

            async def on_retry(self, step_id: str, attempt: int, error: Exception) -> None:
                events.append(
                    BeddelEvent(
                        event_type=EventType.RETRY,
                        step_id=step_id,
                        data={"attempt": attempt, "error": str(error)},
                    )
                )

        collector = _Collector()
        original_hooks = self._hooks
        self._hooks = [*original_hooks, collector]

        try:
            effective_inputs = inputs or {}
            context = ExecutionContext(
                workflow_id=workflow.id,
                inputs=effective_inputs,
            )
            if self._provider is not None:
                context.metadata["llm_provider"] = self._provider
            context.metadata["lifecycle_hooks"] = self._hooks

            await self._dispatch_hook("on_workflow_start", workflow.id, effective_inputs)
            for event in events:
                yield event
            events.clear()

            for step in workflow.steps:
                await self._execute_step(step, context)

                for event in events:
                    yield event
                events.clear()

                # Consume streaming results and yield TEXT_CHUNK events.
                step_result = context.step_results.get(step.id)
                if step.stream and isinstance(step_result, dict) and "stream" in step_result:
                    async for chunk in step_result["stream"]:
                        yield BeddelEvent(
                            event_type=EventType.TEXT_CHUNK,
                            step_id=step.id,
                            data={"text": chunk},
                        )

            result: dict[str, Any] = {
                "step_results": dict(context.step_results),
                "metadata": dict(context.metadata),
            }
            await self._dispatch_hook("on_workflow_end", workflow.id, result)
            for event in events:
                yield event
            events.clear()
        finally:
            self._hooks = original_hooks

    async def _execute_step(self, step: Step, context: ExecutionContext) -> Any:
        """Execute a single workflow step, with optional conditional branching.

        If the step has an ``if_condition``, it is evaluated first.  When
        truthy the step's primitive runs and any ``then_steps`` are executed
        afterwards.  When falsy the primitive is skipped and ``else_steps``
        are executed instead.  Steps without a condition run unconditionally.

        Args:
            step: The step definition to execute.
            context: Mutable execution context for the current workflow run.

        Returns:
            The primitive's return value, or ``None`` when the step is
            skipped due to a falsy condition.

        Raises:
            ExecutionError: ``BEDDEL-EXEC-002`` when the step fails.
        """
        context.current_step_id = step.id
        await self._dispatch_hook("on_step_start", step.id, step.primitive)

        try:
            if step.if_condition is not None:
                condition_met = self._evaluate_condition(step.if_condition, context)
                if condition_met:
                    result = await self._run_with_timeout(step, context)
                    if step.then_steps:
                        await self._execute_steps(step.then_steps, context)
                else:
                    result = None
                    context.step_results[step.id] = None
                    if step.else_steps:
                        await self._execute_steps(step.else_steps, context)
            else:
                result = await self._run_with_timeout(step, context)

            await self._dispatch_hook("on_step_end", step.id, result)
            return result
        except Exception as exc:
            await self._dispatch_hook("on_error", step.id, exc)
            result = await self._apply_strategy(step, exc, context)
            context.step_results[step.id] = result
            await self._dispatch_hook("on_step_end", step.id, result)
            return result

    async def _dispatch_hook(self, method_name: str, *args: Any) -> None:
        """Call a lifecycle hook method on all registered hooks.

        Each hook call is wrapped in a try/except so that a misbehaving
        hook never breaks workflow execution.  Exceptions from hooks are
        logged but not re-raised.

        Args:
            method_name: Name of the :class:`ILifecycleHook` method to call.
            *args: Positional arguments forwarded to the hook method.
        """
        for hook in self._hooks:
            try:
                method = getattr(hook, method_name)
                await method(*args)
            except Exception:
                logger.warning(
                    "Lifecycle hook %s.%s raised an exception (ignored)",
                    type(hook).__name__,
                    method_name,
                    exc_info=True,
                )

    async def _run_primitive(self, step: Step, context: ExecutionContext) -> Any:
        """Resolve config, look up the primitive, execute it, and store the result."""
        resolved_config = self._resolver.resolve(step.config, context)
        primitive: IPrimitive = self._registry.get(step.primitive)
        result = await primitive.execute(resolved_config, context)
        context.step_results[step.id] = result
        return result

    async def _run_with_timeout(self, step: Step, context: ExecutionContext) -> Any:
        """Run a primitive with optional timeout enforcement.

        When ``step.timeout`` is set, wraps the primitive execution in
        :func:`asyncio.wait_for`.  A timeout converts the resulting
        :class:`asyncio.TimeoutError` into an :class:`ExecutionError`
        with code ``BEDDEL-EXEC-005`` so that the normal error-strategy
        pipeline can handle it.

        Args:
            step: The step definition (may carry a ``timeout`` value).
            context: Mutable execution context for the current workflow run.

        Returns:
            The primitive's return value.

        Raises:
            ExecutionError: ``BEDDEL-EXEC-005`` when the step exceeds its
                timeout.
        """
        if step.timeout is not None:
            try:
                return await asyncio.wait_for(
                    self._run_primitive(step, context),
                    timeout=step.timeout,
                )
            except TimeoutError:
                raise ExecutionError(
                    code="BEDDEL-EXEC-005",
                    message=f"Step '{step.id}' timed out after {step.timeout}s",
                    details={
                        "step_id": step.id,
                        "primitive": step.primitive,
                        "timeout": step.timeout,
                    },
                ) from None
        return await self._run_primitive(step, context)

    def _evaluate_condition(self, condition: str, context: ExecutionContext) -> bool:
        """Resolve a condition string and evaluate its truthiness.

        The *condition* is first resolved through the
        :class:`VariableResolver` (handling ``$input.*``,
        ``$stepResult.*``, ``$env.*`` references).  The resolved value is
        then coerced to a boolean:

        * **Strings**: ``"true"`` (case-insensitive) → ``True``;
          ``"false"`` (case-insensitive) → ``False``; empty string →
          ``False``; any other non-empty string → ``True``.
        * **Non-strings**: standard Python truthiness (``bool(value)``).

        Args:
            condition: A raw condition expression, possibly containing
                variable references.
            context: The current execution context used for resolution.

        Returns:
            ``True`` if the resolved value is truthy, ``False`` otherwise.
        """
        resolved = self._resolver.resolve(condition, context)

        if isinstance(resolved, str):
            lower = resolved.lower()
            if lower == "true":
                return True
            if lower == "false":
                return False
            return bool(resolved)  # empty string → False

        return bool(resolved)

    async def _execute_steps(self, steps: list[Step], context: ExecutionContext) -> None:
        """Execute a list of steps sequentially.

        Used internally to run ``then_steps`` and ``else_steps`` branches
        during conditional execution.

        Args:
            steps: Ordered list of steps to execute.
            context: Mutable execution context for the current workflow run.
        """
        for step in steps:
            await self._execute_step(step, context)

    async def _apply_strategy(
        self, step: Step, error: Exception, context: ExecutionContext
    ) -> Any | None:
        """Dispatch to the appropriate error-handling strategy for a step.

        Inspects ``step.execution_strategy.type`` and delegates to the
        corresponding handler.  The ``fail`` strategy re-raises immediately;
        ``skip`` returns ``None``; ``retry`` attempts exponential back-off;
        ``fallback`` executes an alternative step.

        Args:
            step: The step that failed.
            error: The exception raised during step execution.
            context: Mutable execution context for the current workflow run.

        Returns:
            The recovery result (``None`` for skip, primitive result for
            retry/fallback).

        Raises:
            ExecutionError: ``BEDDEL-EXEC-002`` for fail strategy,
                ``BEDDEL-EXEC-003`` when retries are exhausted,
                ``BEDDEL-EXEC-004`` when no fallback step is defined.
        """
        strategy = step.execution_strategy.type

        if strategy == StrategyType.SKIP:
            logger.warning(
                "Step '%s' failed but strategy is SKIP — continuing: %s",
                step.id,
                error,
            )
            return None

        if strategy == StrategyType.RETRY:
            return await self._retry_step(step, error, context)

        if strategy == StrategyType.FALLBACK:
            return await self._fallback_step(step, error, context)

        # StrategyType.FAIL (default) and any unhandled strategy type
        raise ExecutionError(
            code="BEDDEL-EXEC-002",
            message=f"Step '{step.id}' failed: {error}",
            details={
                "step_id": step.id,
                "primitive": step.primitive,
                "original_error": str(error),
                "error_type": type(error).__name__,
            },
        ) from error

    async def _retry_step(
        self, step: Step, initial_error: Exception, context: ExecutionContext
    ) -> Any:
        """Retry a failed step with exponential back-off and optional jitter.

        Uses the step's :class:`RetryConfig` (or defaults) to determine
        delay timing.  The ``on_retry`` lifecycle hook fires before each
        attempt.

        Args:
            step: The step to retry.
            initial_error: The exception from the original (first) attempt.
            context: Mutable execution context for the current workflow run.

        Returns:
            The primitive's result if a retry succeeds.

        Raises:
            ExecutionError: ``BEDDEL-EXEC-003`` when all retry attempts are
                exhausted.
        """
        config = step.execution_strategy.retry or RetryConfig()
        last_error: Exception = initial_error

        for attempt in range(1, config.max_attempts + 1):
            delay = min(config.backoff_base**attempt, config.backoff_max)
            if config.jitter:
                delay *= random.uniform(0.5, 1.5)  # noqa: S311

            await asyncio.sleep(delay)
            await self._dispatch_hook("on_retry", step.id, attempt, last_error)

            try:
                return await self._run_with_timeout(step, context)
            except Exception as exc:
                last_error = exc

        raise ExecutionError(
            code="BEDDEL-EXEC-003",
            message=f"Step '{step.id}' failed after {config.max_attempts} retries: {last_error}",
            details={
                "step_id": step.id,
                "primitive": step.primitive,
                "max_attempts": config.max_attempts,
                "original_error": str(last_error),
                "error_type": type(last_error).__name__,
            },
        ) from last_error

    async def _fallback_step(self, step: Step, error: Exception, context: ExecutionContext) -> Any:
        """Execute a fallback step when the primary step fails.

        If the step's execution strategy defines a ``fallback_step``, it is
        executed as a normal step.  Otherwise an :class:`ExecutionError` is
        raised.

        Args:
            step: The step whose fallback should be executed.
            error: The exception from the original step execution.
            context: Mutable execution context for the current workflow run.

        Returns:
            The fallback step's result.

        Raises:
            ExecutionError: ``BEDDEL-EXEC-004`` when no fallback step is
                defined or the fallback step itself fails.
        """
        fallback = step.execution_strategy.fallback_step
        if fallback is None:
            raise ExecutionError(
                code="BEDDEL-EXEC-004",
                message=(
                    f"Step '{step.id}' failed with FALLBACK strategy but no fallback step defined"
                ),
                details={
                    "step_id": step.id,
                    "primitive": step.primitive,
                    "original_error": str(error),
                    "error_type": type(error).__name__,
                },
            ) from error

        return await self._execute_step(fallback, context)
