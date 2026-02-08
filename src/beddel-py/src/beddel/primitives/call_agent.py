"""Call-agent primitive — Nested workflow invocation."""

from __future__ import annotations

import logging
import time
from typing import Any

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    ExecutionResult,
    PrimitiveError,
    StepResult,
)

logger = logging.getLogger("beddel.primitives.call_agent")


async def call_agent_primitive(
    config: dict[str, Any],
    context: ExecutionContext,
) -> Any:
    """Invoke a nested workflow by agent ID.

    Retrieves a workflow definition via ``context.metadata["workflow_loader"]``,
    then executes it with a new ``WorkflowExecutor`` using the shared registry.
    Tracks recursion depth via ``context.metadata["call_depth"]``.
    """
    # AC 2: Extract agentId
    if "agentId" not in config:
        raise PrimitiveError(
            "call-agent requires 'agentId' in config",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "call-agent", "hint": "Add agentId field to config"},
        )
    agent_id: str = config["agentId"]

    # AC 3: Extract input (default {})
    input_data: dict[str, Any] = config.get("input", {})

    # AC 8: Recursion depth guard
    max_depth: int = config.get("max_depth", 5)
    current_depth: int = context.metadata.get("call_depth", 0)

    if current_depth >= max_depth:
        raise PrimitiveError(
            f"call-agent max recursion depth exceeded ({current_depth}/{max_depth})",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={
                "primitive": "call-agent",
                "agentId": agent_id,
                "call_depth": current_depth,
                "max_depth": max_depth,
            },
        )

    # AC 4: Retrieve workflow_loader
    workflow_loader = context.metadata.get("workflow_loader")
    if workflow_loader is None:
        raise PrimitiveError(
            "call-agent requires 'workflow_loader' in context.metadata",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "call-agent", "hint": "Provide workflow_loader in metadata"},
        )

    # AC 5: Load workflow definition (propagate ParseError)
    logger.debug(
        "Invoking nested workflow: agentId=%s, depth=%d/%d",
        agent_id, current_depth + 1, max_depth,
    )
    workflow_def = workflow_loader(agent_id)

    # AC 6: Retrieve registry and execute nested workflow
    registry = context.metadata.get("registry")
    if registry is None:
        raise PrimitiveError(
            "call-agent requires 'registry' in context.metadata",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "call-agent", "hint": "Provide registry in metadata"},
        )

    child_metadata = {**context.metadata, "call_depth": current_depth + 1}
    result = await _execute_nested(registry, workflow_def, input_data, child_metadata)

    # AC 7: Return output or wrap error
    if not result.success:
        logger.debug(
            "Nested workflow failed: agentId=%s, depth=%d, error=%s",
            agent_id, current_depth + 1, result.error,
        )
        raise PrimitiveError(
            f"Nested workflow '{agent_id}' failed: {result.error}",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "call-agent", "agentId": agent_id, "error": result.error},
        )

    # AC 9: Log success
    logger.debug(
        "Nested workflow completed: agentId=%s, depth=%d, success=True",
        agent_id, current_depth + 1,
    )
    return result.output


async def _execute_nested(
    registry: Any,
    workflow_def: Any,
    input_data: dict[str, Any],
    metadata: dict[str, Any],
) -> ExecutionResult:
    """Execute a nested workflow with metadata propagation.

    WorkflowExecutor.execute() creates a fresh context without metadata.
    This helper builds the context manually so ``call_depth`` propagates
    to any further nested call-agent invocations.
    """
    from beddel.domain.executor import WorkflowExecutor
    from beddel.domain.resolver import VariableResolver

    executor = WorkflowExecutor(registry=registry)
    start = time.monotonic()

    child_ctx = ExecutionContext(
        input=input_data,
        env=dict(workflow_def.config.environment),
        metadata=metadata,
    )

    step_results: dict[str, StepResult] = {}
    last_output: Any = None

    for step in workflow_def.workflow:
        step_result = await executor.execute_step(step, child_ctx)
        step_results[step.id] = step_result

        if not step_result.success:
            if step.on_error and step.on_error.strategy == "skip":
                continue
            return ExecutionResult(
                workflow_id=child_ctx.workflow_id,
                success=False,
                error=step_result.error,
                step_results=step_results,
                duration_ms=(time.monotonic() - start) * 1000,
            )

        if step.result:
            child_ctx = child_ctx.with_step_result(step.result, step_result.output)
        last_output = step_result.output

    # Resolve return template
    output: Any
    if workflow_def.return_template:
        resolver = VariableResolver()
        output = resolver.resolve_dict(workflow_def.return_template, child_ctx)
    elif workflow_def.workflow and workflow_def.workflow[-1].result is None:
        output = last_output
    else:
        output = child_ctx.step_results

    return ExecutionResult(
        workflow_id=child_ctx.workflow_id,
        success=True,
        output=output,
        step_results=step_results,
        duration_ms=(time.monotonic() - start) * 1000,
    )
