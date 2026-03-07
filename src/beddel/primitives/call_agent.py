"""Call-agent primitive — nested workflow invocation for Beddel workflows.

Provides :class:`CallAgentPrimitive`, which implements
:class:`~beddel.domain.ports.IPrimitive` and enables workflow composition
by loading and executing nested workflows with configurable max depth
and context passing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# SequentialStrategy is imported directly (not via IExecutionStrategy port)
# because the call-agent primitive always runs nested workflows sequentially.
# This is a deliberate coupling — the primitive owns the child execution strategy.
from beddel.domain.errors import PrimitiveError
from beddel.domain.executor import SequentialStrategy, WorkflowExecutor
from beddel.domain.models import DefaultDependencies, ExecutionContext, Workflow
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.domain.resolver import VariableResolver
from beddel.error_codes import (
    PRIM_INVALID_TYPE,
    PRIM_MAX_DEPTH,
    PRIM_MISSING_WORKFLOW,
    PRIM_NOT_FOUND,
)

__all__ = [
    "CallAgentPrimitive",
]

_DEFAULT_MAX_DEPTH = 5


class CallAgentPrimitive(IPrimitive):
    """Nested workflow invocation primitive.

    Loads a child workflow via ``context.deps.workflow_loader``, creates a
    child :class:`ExecutionContext` with inherited dependencies and resolved
    inputs, then executes the nested workflow using :class:`SequentialStrategy`.

    Enforces a configurable ``max_depth`` (default: 5) to prevent infinite
    recursion.  Depth is tracked via ``_call_depth`` in context metadata.

    Config keys:
        workflow (str): Required. Workflow ID to load via workflow_loader.
        inputs (dict): Optional. Inputs to pass to the nested workflow.
            Supports ``$input`` and ``$stepResult`` variable references.
        max_depth (int): Optional. Maximum nesting depth (default: 5).

    Example config::

        {
            "workflow": "summarize-wf",
            "inputs": {"text": "$stepResult.extract.content"},
            "max_depth": 3,
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the call-agent primitive.

        Validates config, checks depth, loads the nested workflow, resolves
        inputs, creates a child context, and runs the nested workflow steps.

        Args:
            config: Primitive configuration containing ``workflow`` (required)
                and optional ``inputs`` and ``max_depth`` keys.
            context: Execution context providing runtime data and dependencies.

        Returns:
            A dict of the nested workflow's step results.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-001`` if workflow_loader is missing.
            PrimitiveError: ``BEDDEL-PRIM-002`` if registry is missing.
            PrimitiveError: ``BEDDEL-PRIM-200`` if max depth is exceeded.
        """
        self._validate_config(config, context)
        workflow_loader = self._get_workflow_loader(context)
        registry = self._get_registry(context)

        max_depth = config.get("max_depth", _DEFAULT_MAX_DEPTH)
        current_depth = context.metadata.get("_call_depth", 0)
        if current_depth >= max_depth:
            raise PrimitiveError(
                code=PRIM_MAX_DEPTH,
                message=(
                    f"Maximum call-agent nesting depth exceeded: "
                    f"current depth {current_depth} >= max depth {max_depth}"
                ),
                details={
                    "primitive": "call-agent",
                    "step_id": context.current_step_id,
                    "current_depth": current_depth,
                    "max_depth": max_depth,
                },
            )

        workflow = workflow_loader(config["workflow"])

        resolved_inputs: dict[str, Any] = {}
        if "inputs" in config:
            resolver = VariableResolver()
            resolved_inputs = resolver.resolve(config["inputs"], context)

        child_context = ExecutionContext(
            workflow_id=workflow.id,
            inputs=resolved_inputs,
            metadata={"_call_depth": current_depth + 1},
            deps=DefaultDependencies(
                llm_provider=context.deps.llm_provider,
                lifecycle_hooks=context.deps.lifecycle_hooks,
                workflow_loader=context.deps.workflow_loader,
                registry=context.deps.registry,
                tool_registry=context.deps.tool_registry,
            ),
        )

        hook_manager = context.deps.lifecycle_hooks
        child_executor = WorkflowExecutor(
            registry=registry,
            provider=context.deps.llm_provider,
            hooks=hook_manager,
        )
        strategy = SequentialStrategy()
        # NOTE: Accessing _execute_step directly is a known coupling point.
        # The alternative (calling executor.execute()) would create its own
        # ExecutionContext, losing our depth-tracking metadata. This trade-off
        # is documented in Story 2.3 Dev Notes. If _execute_step is ever
        # refactored, this call site must be updated.
        await strategy.execute(workflow, child_context, child_executor._execute_step)

        return dict(child_context.step_results)

    @staticmethod
    def _validate_config(config: dict[str, Any], context: ExecutionContext) -> None:
        """Validate required config keys.

        Args:
            config: Primitive configuration dict.
            context: Execution context for error details.

        Raises:
            PrimitiveError: If ``workflow`` key is missing from config.
        """
        if "workflow" not in config:
            raise PrimitiveError(
                code=PRIM_MISSING_WORKFLOW,
                message="Missing required config key 'workflow' for call-agent",
                details={
                    "primitive": "call-agent",
                    "step_id": context.current_step_id,
                },
            )

    @staticmethod
    def _get_workflow_loader(context: ExecutionContext) -> Callable[[str], Workflow]:
        """Extract workflow_loader from context deps.

        Args:
            context: Execution context providing dependencies.

        Returns:
            The workflow_loader callable.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-001`` if workflow_loader is missing.
        """
        if context.deps.workflow_loader is None:
            raise PrimitiveError(
                code=PRIM_NOT_FOUND,
                message=("Missing required dependency 'workflow_loader' for call-agent"),
                details={
                    "primitive": "call-agent",
                    "step_id": context.current_step_id,
                },
            )
        return context.deps.workflow_loader

    @staticmethod
    def _get_registry(context: ExecutionContext) -> PrimitiveRegistry:
        """Extract registry from context deps.

        Args:
            context: Execution context providing dependencies.

        Returns:
            The PrimitiveRegistry instance.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-002`` if registry is missing.
        """
        if context.deps.registry is None:
            raise PrimitiveError(
                code=PRIM_INVALID_TYPE,
                message=("Missing required dependency 'registry' for call-agent"),
                details={
                    "primitive": "call-agent",
                    "step_id": context.current_step_id,
                },
            )
        return context.deps.registry
