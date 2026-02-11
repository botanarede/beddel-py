"""Workflow executor — Async sequential execution with early-return."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator
from collections.abc import AsyncIterator as AsyncIteratorABC
from typing import TYPE_CHECKING, Any

from beddel.domain.models import (
    BeddelError,
    BeddelEvent,
    BeddelEventType,
    ExecutionContext,
    ExecutionError,
    ExecutionResult,
    PrimitiveError,
    StepResult,
)
from beddel.domain.resolver import VariableResolver

if TYPE_CHECKING:
    from beddel.domain.models import StepDefinition, WorkflowDefinition
    from beddel.domain.ports import ILifecycleHook, ILLMProvider, ITracer
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

def _build_error_payload(exc: Exception, step_id: str) -> dict[str, Any]:
    """Build a structured error payload for ERROR events. Never includes tracebacks."""
    if isinstance(exc, BeddelError):
        return {
            "code": str(exc.code),
            "message": str(exc),
            "details": exc.details,
        }
    return {
        "code": "INTERNAL_ERROR",
        "message": f"Step '{step_id}' failed: {exc}",
        "details": {},
    }



class WorkflowExecutor:
    """Orchestrate async sequential execution of workflow steps."""

    def __init__(
        self,
        registry: PrimitiveRegistry,
        resolver: VariableResolver | None = None,
        tracer: ITracer | None = None,
        hooks: list[ILifecycleHook] | None = None,
        provider: ILLMProvider | None = None,
    ) -> None:
        self._registry = registry
        self._resolver = resolver or VariableResolver()
        self._tracer = tracer
        self._hooks = hooks or []
        self._provider = provider

    async def execute(
        self,
        workflow: WorkflowDefinition,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute a workflow definition sequentially."""
        start = time.monotonic()
        metadata: dict[str, Any] = {}
        if self._provider is not None:
            metadata["llm_provider"] = self._provider
        if self._hooks:
            metadata["lifecycle_hooks"] = self._hooks
        context = ExecutionContext(
            input=input_data or {},
            env=dict(workflow.config.environment),
            metadata=metadata,
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

    async def execute_stream(
        self,
        workflow: WorkflowDefinition,
        input_data: dict[str, Any] | None = None,
    ) -> AsyncGenerator[BeddelEvent, None]:
        """Execute a workflow definition, yielding events at each lifecycle point.

        This is the streaming counterpart to :meth:`execute`.  It yields
        :class:`BeddelEvent` instances **and** fires lifecycle hooks at
        every lifecycle point (dual-write).

        On step failure an ``ERROR`` event is yielded and iteration stops.
        If the consumer closes the generator (``GeneratorExit``), a warning
        is logged and the method returns cleanly.
        """
        start = time.monotonic()
        effective_input = input_data or {}
        metadata: dict[str, Any] = {}
        if self._provider is not None:
            metadata["llm_provider"] = self._provider
        if self._hooks:
            metadata["lifecycle_hooks"] = self._hooks
        context = ExecutionContext(
            input=effective_input,
            env=dict(workflow.config.environment),
            metadata=metadata,
        )

        try:
            # ── WORKFLOW_START ──────────────────────────────────────
            for hook in self._hooks:
                await hook.on_workflow_start(workflow, effective_input)
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_START,
                workflow_id=context.workflow_id,
                data={
                    "workflow_name": workflow.metadata.name,
                    "input_keys": list(effective_input.keys()),
                },
            )

            for step in workflow.workflow:
                # Condition check — skip silently (no events)
                if step.condition:
                    resolved = self._resolver.resolve(step.condition, context)
                    if not _evaluate_condition(resolved):
                        continue

                # ── STEP_START ──────────────────────────────────────
                for hook in self._hooks:
                    await hook.on_step_start(step)
                yield BeddelEvent(
                    type=BeddelEventType.STEP_START,
                    workflow_id=context.workflow_id,
                    step_id=step.id,
                    data={"step_type": step.type},
                )

                try:
                    resolved_config = self._resolver.resolve_dict(
                        step.config, context,
                    )
                    primitive_fn = self._registry.get(step.type)
                    output = await primitive_fn(resolved_config, context)

                    # Streaming output (AsyncIterator[str]) → TEXT_CHUNK events
                    if isinstance(output, AsyncIteratorABC):
                        chunks: list[str] = []
                        async for chunk in output:
                            yield BeddelEvent(
                                type=BeddelEventType.TEXT_CHUNK,
                                workflow_id=context.workflow_id,
                                step_id=step.id,
                                data=str(chunk),
                            )
                            chunks.append(str(chunk))
                        step_output: Any = "".join(chunks)
                    else:
                        step_output = output

                    # ── STEP_RESULT ─────────────────────────────────
                    step_result = StepResult(
                        step_id=step.id,
                        output=step_output,
                        success=True,
                        duration_ms=_elapsed_ms(start),
                    )
                    yield BeddelEvent(
                        type=BeddelEventType.STEP_RESULT,
                        workflow_id=context.workflow_id,
                        step_id=step.id,
                        data=step_result.model_dump(mode="json"),
                    )

                    for hook in self._hooks:
                        await hook.on_step_end(step, step_output)

                    # ── STEP_END ────────────────────────────────────
                    yield BeddelEvent(
                        type=BeddelEventType.STEP_END,
                        workflow_id=context.workflow_id,
                        step_id=step.id,
                    )

                    # Update context for downstream steps
                    if step.result:
                        context = context.with_step_result(
                            step.result, step_output,
                        )

                except Exception as exc:
                    # ── ERROR ────────────────────────────────────────
                    error_payload = _build_error_payload(exc, step.id)
                    for hook in self._hooks:
                        await hook.on_error(exc)
                    yield BeddelEvent(
                        type=BeddelEventType.ERROR,
                        workflow_id=context.workflow_id,
                        step_id=step.id,
                        data=error_payload,
                    )
                    return  # stop iteration on error

            # ── WORKFLOW_END ────────────────────────────────────────
            for hook in self._hooks:
                await hook.on_workflow_end(workflow, None)
            yield BeddelEvent(
                type=BeddelEventType.WORKFLOW_END,
                workflow_id=context.workflow_id,
                data={
                    "success": True,
                    "duration_ms": round(_elapsed_ms(start), 2),
                },
            )

        except GeneratorExit:
            logger.warning("Client disconnected during streaming execution")
            return


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
