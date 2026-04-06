"""Workflow executor for the Beddel SDK.

Orchestrates sequential execution of workflow steps, resolving variable
references, dispatching lifecycle hooks, and collecting results into an
:class:`~beddel.domain.models.ExecutionContext`.

Only stdlib + pydantic + domain imports are allowed in this module
(domain core rule).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import re
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.errors import BudgetError, ExecutionError, TracingError
from beddel.domain.models import (
    SKIPPED,
    BeddelEvent,
    BudgetStatus,
    DefaultDependencies,
    EventType,
    ExecutionContext,
    RetryConfig,
    Step,
    StrategyType,
    Workflow,
)
from beddel.domain.ports import (
    IExecutionStrategy,
    IHookManager,
    ILifecycleHook,
    IPrimitive,
    StepRunner,
)
from beddel.domain.registry import PrimitiveRegistry
from beddel.domain.resolver import VariableResolver
from beddel.domain.tracing_utils import extract_token_usage
from beddel.error_codes import (
    BUDGET_EXCEEDED,
    CB_CIRCUIT_OPEN,
    EXEC_CONDITION_TYPE_ERROR,
    EXEC_DELEGATE_FAILED,
    EXEC_DELEGATE_INVALID,
    EXEC_NO_FALLBACK,
    EXEC_RETRIES_EXHAUSTED,
    EXEC_STEP_FAILED,
    EXEC_TIMEOUT,
)

__all__ = [
    "SequentialStrategy",
    "WorkflowExecutor",
]

logger = logging.getLogger(__name__)

_COMPARISON_RE = re.compile(r"^(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$")


def _parse_literal(value: str) -> int | float | bool | str:
    """Parse a literal value from the right side of a comparison.

    Strips surrounding single or double quotes, then attempts to
    interpret *value* as an int, float, or boolean
    (``"true"``/``"false"`` case-insensitive).  Falls back to returning
    the raw string.

    Args:
        value: The string to parse.

    Returns:
        The parsed literal as its native Python type.
    """
    # Strip surrounding quotes if present.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _extract_provider(model: str) -> str:
    """Extract provider name from model identifier.

    ``'openai/gpt-4o'`` → ``'openai'``, ``'gpt-4o'`` → ``'gpt-4o'``.
    """
    if "/" in model:
        return model.split("/", 1)[0]
    return model


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
        step_runner: StepRunner,
    ) -> None:
        """Execute steps sequentially in declaration order.

        Args:
            workflow: The workflow definition containing steps to execute.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.
            step_runner: :data:`StepRunner` callback that executes a single
                step with full lifecycle handling.
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

    The execution strategy is resolved at runtime from
    ``context.deps.execution_strategy``, falling back to
    :class:`SequentialStrategy` when ``None``.

    Public methods:

    - :meth:`execute` — run a workflow end-to-end, returning collected results.
    - :meth:`execute_stream` — stream workflow execution as events.
    - :meth:`execute_step_with_context` — execute a single step against an
      existing :class:`ExecutionContext`.  Useful for primitives (e.g.
      ``call-agent``) that need to drive step execution without creating a
      new context.

    Args:
        registry: Primitive registry used to look up step primitives.
        deps: Optional pre-built :class:`DefaultDependencies` instance.
            When provided, :meth:`execute` and :meth:`execute_stream` use
            it as the base dependency bag, overlaying only
            ``execution_strategy`` and ``lifecycle_hooks`` at runtime.
            When ``None`` (default), a minimal
            :class:`DefaultDependencies` is created with only
            ``lifecycle_hooks`` and ``execution_strategy``.

    Example::

        executor = WorkflowExecutor(registry, deps=DefaultDependencies(
            llm_provider=my_llm,
        ))
        result = await executor.execute(workflow, {"topic": "AI"})
    """

    def __init__(
        self,
        registry: PrimitiveRegistry,
        deps: DefaultDependencies | None = None,
    ) -> None:
        """Initialise the executor.

        Args:
            registry: Primitive registry for step primitive look-ups.
            deps: Optional pre-built :class:`DefaultDependencies`.  When
                provided, used as the base for ``context.deps`` in
                :meth:`execute` and :meth:`execute_stream`, with
                ``execution_strategy`` and ``lifecycle_hooks`` overlaid
                at runtime.  When ``None``, a minimal
                :class:`DefaultDependencies` is created.
        """
        self._registry = registry
        self._hook_manager: IHookManager = (
            deps.lifecycle_hooks
            if deps is not None and deps.lifecycle_hooks is not None
            else IHookManager()
        )
        self._deps = deps
        self._resolver = VariableResolver()

    def _make_context_deps(
        self,
        execution_strategy: IExecutionStrategy | None = None,
    ) -> DefaultDependencies:
        """Build the :class:`DefaultDependencies` for a workflow run.

        When ``self._deps`` was provided at construction time, it is used
        as the base dependency bag with all fields forwarded.
        ``execution_strategy`` is overlaid (the method parameter wins
        when non-``None``, otherwise the value from ``self._deps`` is
        preserved).  ``lifecycle_hooks`` always comes from
        ``self._hook_manager`` so that runtime-added hooks (e.g. the
        streaming ``_Collector``) are visible.

        When ``self._deps`` is ``None``, a minimal
        :class:`DefaultDependencies` is created with only
        ``lifecycle_hooks`` and ``execution_strategy``.

        Args:
            execution_strategy: Optional execution strategy override.

        Returns:
            A fully-populated :class:`DefaultDependencies` instance.
        """
        if self._deps is not None:
            return DefaultDependencies(
                llm_provider=self._deps.llm_provider,
                lifecycle_hooks=self._hook_manager,
                execution_strategy=(
                    execution_strategy
                    if execution_strategy is not None
                    else self._deps.execution_strategy
                ),
                delegate_model=self._deps.delegate_model,
                tracer=self._deps.tracer,
                workflow_loader=self._deps.workflow_loader,
                registry=self._deps.registry,
                tool_registry=self._deps.tool_registry,
                agent_adapter=self._deps.agent_adapter,
                agent_registry=self._deps.agent_registry,
                context_reducer=self._deps.context_reducer,
                circuit_breaker=self._deps.circuit_breaker,
                event_store=self._deps.event_store,
                mcp_registry=self._deps.mcp_registry,
                tier_router=self._deps.tier_router,
                budget_enforcer=self._deps.budget_enforcer,
                approval_gate=self._deps.approval_gate,
                pii_tokenizer=self._deps.pii_tokenizer,
                state_store=self._deps.state_store,
                memory_provider=self._deps.memory_provider,
                knowledge_provider=self._deps.knowledge_provider,
                decision_store=self._deps.decision_store,
                kit_manifests=self._deps.kit_manifests,
            )
        return DefaultDependencies(
            lifecycle_hooks=self._hook_manager,
            execution_strategy=execution_strategy,
        )

    async def execute(
        self,
        workflow: Workflow,
        inputs: dict[str, Any] | None = None,
        *,
        execution_strategy: IExecutionStrategy | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow sequentially, returning collected results.

        Creates an :class:`ExecutionContext`, injects dependencies via
        ``context.deps``, iterates steps in order, and returns the
        accumulated step results and metadata.

        When the executor was constructed with a ``deps`` argument, that
        instance is used as the base dependency bag.  The
        ``execution_strategy`` parameter is overlaid on top, and
        ``lifecycle_hooks`` always comes from the executor's hook manager
        (so that runtime-added hooks like the streaming collector are
        visible).  When ``deps`` was not provided, a minimal
        :class:`DefaultDependencies` is created.

        When ``context.deps.tracer`` is not ``None``, a
        ``beddel.workflow`` span wraps the entire execution with the
        ``beddel.workflow_id`` attribute.  Tracing failures are silently
        logged and never propagate.

        Args:
            workflow: The workflow definition to execute.
            inputs: Optional input dict available as ``$input.*`` in step
                configs.
            execution_strategy: Optional execution strategy override.  When
                provided, takes precedence over any strategy stored in
                ``context.deps``.  Defaults to :class:`SequentialStrategy`
                when both are ``None``.

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

        context.deps = self._make_context_deps(execution_strategy)
        context.metadata["_workflow_allowed_tools"] = workflow.allowed_tools

        tracer = context.deps.tracer
        workflow_span: Any = None
        if tracer is not None:
            try:
                workflow_span = tracer.start_span(
                    "beddel.workflow",
                    {"beddel.workflow_id": workflow.id},
                )
            except TracingError as exc:
                if exc.fail_silent:
                    logger.warning("Tracing start_span failed (ignored)", exc_info=True)
                else:
                    raise

        try:
            await self._dispatch_hook("on_workflow_start", workflow.id, effective_inputs)

            strategy = context.deps.execution_strategy or SequentialStrategy()
            await strategy.execute(workflow, context, self._execute_step)

            result: dict[str, Any] = {
                "step_results": dict(context.step_results),
                "metadata": dict(context.metadata),
            }

            await self._dispatch_hook("on_workflow_end", workflow.id, result)
            return result
        finally:
            if tracer is not None and workflow_span is not None:
                try:
                    tracer.end_span(workflow_span)
                except TracingError as exc:
                    if exc.fail_silent:
                        logger.warning("Tracing end_span failed (ignored)", exc_info=True)
                    else:
                        raise

    async def execute_stream(
        self,
        workflow: Workflow,
        inputs: dict[str, Any] | None = None,
        *,
        execution_strategy: IExecutionStrategy | None = None,
    ) -> AsyncGenerator[BeddelEvent, None]:
        """Stream workflow execution as a sequence of events.

        Mirrors the logic of :meth:`execute` but yields
        :class:`~beddel.domain.models.BeddelEvent` instances at each
        lifecycle point instead of collecting results into a dict.

        A temporary :class:`ILifecycleHook` is installed to capture events
        produced by the execution internals (``_execute_step``,
        ``_retry_step``, etc.).  Events are pushed to an
        :class:`asyncio.Queue` and yielded in real-time as the strategy
        executes, rather than being batched after completion.

        For steps with ``stream=True``, the stored async-generator result
        is consumed and each chunk is yielded as a ``TEXT_CHUNK`` event.

        Dependency resolution follows the same rules as :meth:`execute`:
        when the executor was constructed with ``deps``, that instance is
        used as the base with ``execution_strategy`` overlaid and
        ``lifecycle_hooks`` always sourced from the executor's hook
        manager (critical — the ``_Collector`` hook is added at runtime).

        When ``context.deps.tracer`` is not ``None``, a
        ``beddel.workflow`` span wraps the entire streaming execution
        with the ``beddel.workflow_id`` attribute.

        Args:
            workflow: The workflow definition to execute.
            inputs: Optional input dict available as ``$input.*`` in step
                configs.
            execution_strategy: Optional execution strategy override.  When
                provided, takes precedence over any strategy stored in
                ``context.deps``.  Defaults to :class:`SequentialStrategy`
                when both are ``None``.

        Yields:
            :class:`BeddelEvent` instances for workflow start/end, step
            start/end, errors, retries, and text chunks.
        """
        # Unbounded queue — backpressure is not enforced. For TEXT_CHUNK-heavy
        # flows, consider switching to a bounded queue with await queue.put()
        # (hooks are already async, so this is safe). Deferred per architect
        # review (Story 4.0g F9).
        queue: asyncio.Queue[BeddelEvent | None] = asyncio.Queue()

        class _Collector(ILifecycleHook):
            """Internal hook that pushes events to a queue for real-time streaming.

            Note: ``on_decision`` is intentionally not overridden — decision
            events are not surfaced in the SSE stream.  Decision capture was
            delivered in Epic 7 Story 7.1 (decision-centric runtime).  To
            surface decisions in SSE, add an ``on_decision`` override here
            to emit a ``DECISION`` BeddelEvent.
            """

            def __init__(self, q: asyncio.Queue[BeddelEvent | None]) -> None:
                self._queue = q

            async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
                self._queue.put_nowait(
                    BeddelEvent(
                        event_type=EventType.WORKFLOW_START,
                        data={"workflow_id": workflow_id, "inputs": inputs},
                    )
                )

            async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
                self._queue.put_nowait(
                    BeddelEvent(
                        event_type=EventType.WORKFLOW_END,
                        data={"workflow_id": workflow_id},
                    )
                )

            async def on_step_start(self, step_id: str, primitive: str) -> None:
                self._queue.put_nowait(
                    BeddelEvent(
                        event_type=EventType.STEP_START,
                        step_id=step_id,
                        data={"primitive": primitive},
                    )
                )

            async def on_step_end(self, step_id: str, result: Any) -> None:
                self._queue.put_nowait(
                    BeddelEvent(
                        event_type=EventType.STEP_END,
                        step_id=step_id,
                        data={"result": result},
                    )
                )

            async def on_error(self, step_id: str, error: Exception) -> None:
                self._queue.put_nowait(
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
                self._queue.put_nowait(
                    BeddelEvent(
                        event_type=EventType.RETRY,
                        step_id=step_id,
                        data={"attempt": attempt, "error": str(error)},
                    )
                )

        collector = _Collector(queue)
        await self._hook_manager.add_hook(collector)

        try:
            effective_inputs = inputs or {}
            context = ExecutionContext(
                workflow_id=workflow.id,
                inputs=effective_inputs,
            )
            context.deps = self._make_context_deps(execution_strategy)
            context.metadata["_workflow_allowed_tools"] = workflow.allowed_tools

            tracer = context.deps.tracer
            workflow_span: Any = None
            if tracer is not None:
                try:
                    workflow_span = tracer.start_span(
                        "beddel.workflow",
                        {"beddel.workflow_id": workflow.id},
                    )
                except TracingError as exc:
                    if exc.fail_silent:
                        logger.warning("Tracing start_span failed (ignored)", exc_info=True)
                    else:
                        raise

            task: asyncio.Task[None] | None = None
            try:

                async def _run_strategy() -> None:
                    """Execute the full workflow lifecycle in a background task.

                    Dispatches workflow_start, runs the strategy, consumes
                    streaming step results, dispatches workflow_end, and
                    pushes the sentinel to signal completion.
                    """
                    try:
                        await self._dispatch_hook(
                            "on_workflow_start",
                            workflow.id,
                            effective_inputs,
                        )

                        strategy = context.deps.execution_strategy or SequentialStrategy()
                        await strategy.execute(
                            workflow,
                            context,
                            self._execute_step,
                        )

                        # Consume streaming results in execution order.
                        step_map = {s.id: s for s in workflow.steps}
                        for step_id, step_result in context.step_results.items():
                            step_def = step_map.get(step_id)
                            if (
                                step_def
                                and step_def.stream
                                and isinstance(step_result, dict)
                                and "stream" in step_result
                            ):
                                async for chunk in step_result["stream"]:
                                    queue.put_nowait(
                                        BeddelEvent(
                                            event_type=EventType.TEXT_CHUNK,
                                            step_id=step_id,
                                            data={"text": chunk},
                                        )
                                    )

                        result: dict[str, Any] = {
                            "step_results": dict(context.step_results),
                            "metadata": dict(context.metadata),
                        }
                        await self._dispatch_hook(
                            "on_workflow_end",
                            workflow.id,
                            result,
                        )
                    finally:
                        queue.put_nowait(None)  # Sentinel — always sent

                task = asyncio.create_task(_run_strategy())

                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield event

                # Propagate any strategy execution error.
                await task
            finally:
                # Cancel background task if generator was abandoned early.
                if task is not None and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                if tracer is not None and workflow_span is not None:
                    try:
                        tracer.end_span(workflow_span)
                    except TracingError as exc:
                        if exc.fail_silent:
                            logger.warning("Tracing end_span failed (ignored)", exc_info=True)
                        else:
                            raise
        finally:
            await self._hook_manager.remove_hook(collector)

    async def execute_step_with_context(self, step: Step, context: ExecutionContext) -> Any:
        """Execute a single workflow step against an existing context.

        This is the public entry point for running one step with full
        lifecycle handling (condition evaluation, timeout, error strategies,
        tracing, hooks).  It is intended for callers — such as the
        ``call-agent`` primitive — that already own an
        :class:`ExecutionContext` and need to drive step execution without
        creating a new one.

        If the step has an ``if_condition``, it is evaluated first.  When
        truthy the step's primitive runs and any ``then_steps`` are executed
        afterwards.  When falsy the primitive is skipped and ``else_steps``
        are executed instead.  Steps without a condition run unconditionally.

        When ``context.deps.tracer`` is not ``None``, a
        ``beddel.step.{step_id}`` span wraps the step execution with
        ``beddel.step_id``, ``beddel.primitive``, and
        ``beddel.execution_strategy`` attributes.  Token usage attributes
        (``gen_ai.usage.*``) are added when the step result contains a
        ``usage`` dict.  On error, ``error`` and ``error.message``
        attributes are set before the span ends.

        Args:
            step: The step definition to execute.
            context: Mutable execution context for the current workflow run.

        Returns:
            The primitive's return value, or :data:`SKIPPED` when the step
            is skipped due to a falsy condition.

        Raises:
            ExecutionError: ``BEDDEL-EXEC-002`` when the step fails.
        """
        context.current_step_id = step.id
        await self._dispatch_hook("on_step_start", step.id, step.primitive)

        # --- Circuit breaker check (LLM primitives only) ---
        cb = context.deps.circuit_breaker
        _cb_provider: str = ""
        _cb_active = cb is not None and step.primitive in ("llm", "chat")
        if _cb_active:
            assert cb is not None  # narrowing for mypy
            _cb_provider = _extract_provider(step.config.get("model", ""))
            if _cb_provider and cb.is_open(_cb_provider):
                raise ExecutionError(
                    CB_CIRCUIT_OPEN,
                    f"Circuit breaker open for provider: {_cb_provider}",
                    details={"provider": _cb_provider, "state": cb.state(_cb_provider)},
                )

        tracer = context.deps.tracer
        step_span: Any = None
        if tracer is not None:
            try:
                step_span = tracer.start_span(
                    f"beddel.step.{step.id}",
                    {
                        "beddel.step_id": step.id,
                        "beddel.primitive": step.primitive,
                        "beddel.execution_strategy": step.execution_strategy.type.value,
                    },
                )
            except TracingError as exc:
                if exc.fail_silent:
                    logger.warning("Tracing start_span failed (ignored)", exc_info=True)
                else:
                    raise

        try:
            if step.if_condition is not None:
                condition_met = self._evaluate_condition(step.if_condition, context)
                if condition_met:
                    result = await self._run_with_timeout(step, context)
                    if step.then_steps:
                        await self._execute_steps(step.then_steps, context)
                else:
                    result = SKIPPED
                    context.step_results[step.id] = SKIPPED
                    if step.else_steps:
                        await self._execute_steps(step.else_steps, context)
            else:
                result = await self._run_with_timeout(step, context)

            await self._dispatch_hook("on_step_end", step.id, result)

            # --- Budget enforcement ---
            be = context.deps.budget_enforcer
            if be is not None and isinstance(result, dict) and "usage" in result:
                be.track_usage(step.id, result["usage"])
                budget_status = be.check_budget()
                if budget_status == BudgetStatus.EXCEEDED:
                    raise BudgetError(
                        BUDGET_EXCEEDED,
                        f"Budget exceeded after step '{step.id}'",
                        {
                            "step_id": step.id,
                            "cumulative_cost": be.cumulative_cost,
                            "max_cost_usd": be.max_cost_usd,
                        },
                    )
                if budget_status == BudgetStatus.DEGRADED and not context.metadata.get(
                    "_budget_degraded"
                ):
                    context.metadata["_budget_degraded"] = True
                    context.metadata["_degradation_model"] = be.degradation_model
                    await self._dispatch_hook(
                        "on_budget_threshold",
                        context.workflow_id,
                        be.cumulative_cost,
                        be.degradation_threshold,
                    )

            # --- Circuit breaker: record success ---
            if _cb_active and _cb_provider:
                assert cb is not None
                state_before = cb.state(_cb_provider)
                cb.record_success(_cb_provider)
                state_after = cb.state(_cb_provider)
                if state_before == "half-open" and state_after == "closed":
                    await self._dispatch_hook(
                        "on_step_end",
                        step.id,
                        BeddelEvent(
                            event_type=EventType.CIRCUIT_CLOSE,
                            data={"provider": _cb_provider, "state": state_after},
                        ),
                    )
            return result
        except Exception as exc:
            # --- Circuit breaker: record failure ---
            if _cb_active and _cb_provider:
                assert cb is not None
                state_before = cb.state(_cb_provider)
                cb.record_failure(_cb_provider)
                state_after = cb.state(_cb_provider)
                if state_before != "open" and state_after == "open":
                    await self._dispatch_hook(
                        "on_step_end",
                        step.id,
                        BeddelEvent(
                            event_type=EventType.CIRCUIT_OPEN,
                            data={"provider": _cb_provider, "state": state_after},
                        ),
                    )

            if tracer is not None and step_span is not None:
                try:
                    tracer.end_span(
                        step_span,
                        {"error": True, "error.message": str(exc)},
                    )
                except TracingError as tracing_exc:
                    if tracing_exc.fail_silent:
                        logger.warning("Tracing error span failed (ignored)", exc_info=True)
                    else:
                        raise
                step_span = None  # Prevent double-end in finally

            await self._dispatch_hook("on_error", step.id, exc)
            result = await self._apply_strategy(step, exc, context)
            context.step_results[step.id] = result
            await self._dispatch_hook("on_step_end", step.id, result)
            return result
        finally:
            if tracer is not None and step_span is not None:
                try:
                    step_result = context.step_results.get(step.id)
                    end_attrs = (
                        extract_token_usage(step_result) if isinstance(step_result, dict) else {}
                    )
                    tracer.end_span(step_span, end_attrs or None)
                except TracingError as exc:
                    if exc.fail_silent:
                        logger.warning("Tracing end_span failed (ignored)", exc_info=True)
                    else:
                        raise

    async def _execute_step(self, step: Step, context: ExecutionContext) -> Any:
        """Execute a single step (private delegate).

        Retained for backward compatibility with internal callers
        (``_execute_steps``, strategy callbacks).  Delegates entirely to
        :meth:`execute_step_with_context`.

        Args:
            step: The step definition to execute.
            context: Mutable execution context for the current workflow run.

        Returns:
            The primitive's return value, or :data:`SKIPPED` when the step
            is skipped due to a falsy condition.
        """
        return await self.execute_step_with_context(step, context)

    async def _dispatch_hook(self, method_name: str, *args: Any) -> None:
        """Dispatch a lifecycle event via the hook manager.

        Delegates to the corresponding method on ``self._hook_manager``
        (an :class:`IHookManager` instance).  The manager fans out to all
        registered hooks and handles per-hook error isolation internally.

        Args:
            method_name: Name of the :class:`ILifecycleHook` method to call.
            *args: Positional arguments forwarded to the hook method.
        """
        try:
            method = getattr(self._hook_manager, method_name)
            await method(*args)
        except Exception:
            logger.warning(
                "Lifecycle hook dispatch %s raised an exception (ignored)",
                method_name,
                exc_info=True,
            )

    async def _run_primitive(self, step: Step, context: ExecutionContext) -> Any:
        """Resolve config, look up the primitive, execute it, and store the result.

        When ``context.deps.tracer`` is not ``None``, a
        ``beddel.primitive.{primitive_name}`` span wraps the primitive
        invocation with ``beddel.primitive``, ``beddel.model``, and
        ``beddel.provider`` attributes (model/provider extracted from
        ``step.config`` when present).

        Args:
            step: The step definition whose primitive to execute.
            context: Mutable execution context for the current workflow run.

        Returns:
            The primitive's return value.
        """
        tracer = context.deps.tracer
        prim_span: Any = None
        if tracer is not None:
            try:
                attrs: dict[str, Any] = {"beddel.primitive": step.primitive}
                model = step.config.get("model")
                if isinstance(model, str):
                    attrs["beddel.model"] = model
                    if "/" in model:
                        attrs["beddel.provider"] = model.split("/", 1)[0]
                prim_span = tracer.start_span(f"beddel.primitive.{step.primitive}", attrs)
            except TracingError as exc:
                if exc.fail_silent:
                    logger.warning("Tracing start_span failed (ignored)", exc_info=True)
                else:
                    raise

        try:
            resolved_config = self._resolver.resolve(step.config, context)
            primitive: IPrimitive = self._registry.get(step.primitive)
            result = await primitive.execute(resolved_config, context)
            context.step_results[step.id] = result
            return result
        finally:
            if tracer is not None and prim_span is not None:
                try:
                    tracer.end_span(prim_span)
                except TracingError as exc:
                    if exc.fail_silent:
                        logger.warning("Tracing end_span failed (ignored)", exc_info=True)
                    else:
                        raise

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
                    code=EXEC_TIMEOUT,
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

        First attempts to match a comparison expression of the form
        ``<left> <op> <right>`` where ``<op>`` is one of ``==``, ``!=``,
        ``>``, ``<``, ``>=``, ``<=``.  The left side is resolved via
        :class:`VariableResolver`; the right side is parsed as a literal
        (int, float, bool, or string).

        When no comparison operator is found, the condition is resolved
        as a single value and coerced to a boolean:

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
        match = _COMPARISON_RE.match(condition)
        if match:
            left_expr, operator, right_expr = match.group(1), match.group(2), match.group(3)
            left = self._resolver.resolve(left_expr.strip(), context)
            right = _parse_literal(right_expr.strip())

            try:
                if operator == "==":
                    return bool(left == right)
                if operator == "!=":
                    return bool(left != right)
                if operator == ">":
                    return bool(left > right)
                if operator == "<":
                    return bool(left < right)
                if operator == ">=":
                    return bool(left >= right)
                if operator == "<=":
                    return bool(left <= right)
            except TypeError as exc:
                raise ExecutionError(
                    code=EXEC_CONDITION_TYPE_ERROR,
                    message=(
                        f"Condition comparison failed: "
                        f"{type(left).__name__} {operator} {type(right).__name__}"
                    ),
                    details={
                        "condition": condition,
                        "left_value": repr(left),
                        "left_type": type(left).__name__,
                        "right_value": repr(right),
                        "right_type": type(right).__name__,
                        "operator": operator,
                    },
                ) from exc

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
                ``BEDDEL-EXEC-004`` when no fallback step is defined,
                ``BEDDEL-EXEC-010``/``BEDDEL-EXEC-011`` for delegate failures.
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

        if strategy == StrategyType.DELEGATE:
            return await self._delegate_step(step, error, context)

        # StrategyType.FAIL (default) and any unhandled strategy type
        raise ExecutionError(
            code=EXEC_STEP_FAILED,
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
            code=EXEC_RETRIES_EXHAUSTED,
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
                code=EXEC_NO_FALLBACK,
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

    async def _delegate_step(
        self, step: Step, error: Exception, context: ExecutionContext
    ) -> Any | None:
        """Delegate error recovery to an LLM that chooses retry, skip, or fallback.

        Constructs a structured prompt describing the failure and asks the
        LLM provider (from ``context.deps``) to pick a recovery action.
        The chosen action is then dispatched to the corresponding handler.

        Args:
            step: The step that failed.
            error: The exception raised during step execution.
            context: Mutable execution context for the current workflow run.

        Returns:
            The recovery result (``None`` for skip, primitive result for
            retry/fallback).

        Raises:
            ExecutionError: ``BEDDEL-EXEC-010`` when the LLM provider is
                missing or the LLM call fails.
            ExecutionError: ``BEDDEL-EXEC-011`` when the LLM returns an
                unparseable or invalid action.
        """
        provider = context.deps.llm_provider
        if provider is None:
            raise ExecutionError(
                code=EXEC_DELEGATE_FAILED,
                message=(
                    f"Step '{step.id}' uses DELEGATE strategy but no LLM provider is configured"
                ),
                details={"step_id": step.id},
            ) from error

        actions = ["retry", "skip"]
        if step.execution_strategy.fallback_step is not None:
            actions.append("fallback")

        user_prompt = (
            f"Step: {step.id}\n"
            f"Primitive: {step.primitive}\n"
            f"Error: {error}\n"
            f"Error type: {type(error).__name__}\n"
            f"Available actions: {', '.join(actions)}"
        )

        delegate_model = context.deps.delegate_model
        try:
            result = await provider.complete(
                model=delegate_model,
                messages=[
                    {
                        "role": "system",
                        "content": f"Respond with exactly one word: {', '.join(actions)}",
                    },
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as llm_err:
            raise ExecutionError(
                code=EXEC_DELEGATE_FAILED,
                message=(
                    f"LLM call failed during DELEGATE recovery for step '{step.id}': {llm_err}"
                ),
                details={"step_id": step.id, "llm_error": str(llm_err)},
            ) from llm_err

        action = result.get("content", "").strip().lower()

        if action == "retry":
            patched_strategy = step.execution_strategy.model_copy(
                update={"retry": RetryConfig(max_attempts=2)}
            )
            patched_step = step.model_copy(update={"execution_strategy": patched_strategy})
            return await self._retry_step(patched_step, error, context)
        if action == "skip":
            logger.warning("Step '%s' failed — DELEGATE chose SKIP: %s", step.id, error)
            return None
        if action == "fallback" and step.execution_strategy.fallback_step is not None:
            return await self._fallback_step(step, error, context)

        raise ExecutionError(
            code=EXEC_DELEGATE_INVALID,
            message=f"DELEGATE strategy for step '{step.id}' returned invalid action: '{action}'",
            details={"step_id": step.id, "raw_response": result.get("content", "")},
        ) from error
