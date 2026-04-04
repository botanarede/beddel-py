"""Call-agent primitive — nested workflow invocation for Beddel workflows.

Provides :class:`CallAgentPrimitive`, which implements
:class:`~beddel.domain.ports.IPrimitive` and enables workflow composition
by loading and executing nested workflows with configurable max depth
and context passing.

When the optional ``coordination`` config key is present, the primitive
switches to multi-agent coordination mode — resolving a named strategy,
building a :class:`CoordinationTask`, and delegating to the strategy's
``coordinate()`` method.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

# SequentialStrategy is imported directly (not via IExecutionStrategy port)
# because the call-agent primitive always runs nested workflows sequentially.
# This is a deliberate coupling — the primitive owns the child execution strategy.
from beddel.constants import CALL_DEPTH_KEY
from beddel.domain.errors import CoordinationError, PrimitiveError
from beddel.domain.executor import SequentialStrategy, WorkflowExecutor
from beddel.domain.models import (
    CoordinationTask,
    DefaultDependencies,
    ExecutionContext,
    Workflow,
)
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry
from beddel.domain.resolver import VariableResolver
from beddel.domain.strategies.coordination import (
    HandoffStrategy,
    ParallelDispatchStrategy,
    SupervisorStrategy,
)
from beddel.error_codes import (
    PRIM_INVALID_TYPE,
    PRIM_MAX_DEPTH,
    PRIM_MISSING_WORKFLOW,
    PRIM_NOT_FOUND,
)

__all__ = [
    "CallAgentPrimitive",
]

logger = logging.getLogger(__name__)

_DEFAULT_MAX_DEPTH = 5

_COORDINATION_STRATEGIES: dict[str, type] = {
    "supervisor": SupervisorStrategy,
    "handoff": HandoffStrategy,
    "parallel-dispatch": ParallelDispatchStrategy,
}


class CallAgentPrimitive(IPrimitive):
    """Nested workflow invocation primitive.

    Loads a child workflow via ``context.deps.workflow_loader``, creates a
    child :class:`ExecutionContext` with inherited dependencies and resolved
    inputs, then executes the nested workflow using :class:`SequentialStrategy`.

    Enforces a configurable ``max_depth`` (default: 5) to prevent infinite
    recursion.  Depth is tracked via ``_call_depth`` in context metadata.

    When the ``coordination`` config key is present, the primitive switches
    to multi-agent coordination mode instead of nested workflow invocation.

    Config keys:
        workflow (str): Required (unless ``coordination`` is present).
            Workflow ID to load via workflow_loader.
        inputs (dict): Optional. Inputs to pass to the nested workflow.
            Supports ``$input`` and ``$stepResult`` variable references.
        max_depth (int): Optional. Maximum nesting depth (default: 5).
        coordination (dict): Optional. Multi-agent coordination config.
            When present, ``workflow`` is not required.

    Example config (nested workflow)::

        {
            "workflow": "summarize-wf",
            "inputs": {"text": "$stepResult.extract.content"},
            "max_depth": 3,
        }

    Example config (coordination)::

        {
            "coordination": {
                "strategy": "supervisor",
                "agents": ["codex", "claude"],
                "config": {"max_handoffs": 3},
                "prompt": "Analyze this codebase",
            }
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the call-agent primitive.

        When ``coordination`` is present in config, delegates to
        :meth:`_execute_coordination`.  Otherwise, validates config,
        checks depth, loads the nested workflow, resolves inputs,
        creates a child context, and runs the nested workflow steps.

        Args:
            config: Primitive configuration.
            context: Execution context providing runtime data and dependencies.

        Returns:
            A dict of the nested workflow's step results, or a dict
            representation of :class:`CoordinationResult` when using
            coordination mode.

        Raises:
            PrimitiveError: Various codes depending on the failure mode.
        """
        if config.get("coordination"):
            return await self._execute_coordination(config, context)

        self._validate_config(config, context)
        workflow_loader = self._get_workflow_loader(context)
        registry = self._get_registry(context)

        max_depth = config.get("max_depth", _DEFAULT_MAX_DEPTH)
        current_depth = context.metadata.get(CALL_DEPTH_KEY, 0)
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
            metadata={CALL_DEPTH_KEY: current_depth + 1},
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
        await strategy.execute(workflow, child_context, child_executor.execute_step_with_context)

        return dict(child_context.step_results)

    async def _execute_coordination(
        self,
        config: dict[str, Any],
        context: ExecutionContext,
    ) -> dict[str, Any]:
        """Execute multi-agent coordination via a named strategy.

        Resolves the strategy class, builds a :class:`CoordinationTask`,
        resolves agents from the registry, and delegates to the strategy.

        Args:
            config: Primitive configuration with ``coordination`` key.
            context: Execution context providing runtime data and dependencies.

        Returns:
            A dict representation of :class:`CoordinationResult`.

        Raises:
            PrimitiveError: If strategy name is missing/invalid, agent
                registry is missing, or an agent is not found.
            CoordinationError: Re-raised as-is from strategy execution.
        """
        coordination = config["coordination"]

        # --- Resolve strategy ---
        strategy_name = coordination.get("strategy")
        if not strategy_name:
            raise PrimitiveError(
                code=PRIM_NOT_FOUND,
                message="Missing required 'strategy' in coordination config",
                details={
                    "primitive": "call-agent",
                    "step_id": context.current_step_id,
                },
            )

        strategy_cls = _COORDINATION_STRATEGIES.get(strategy_name)
        if strategy_cls is None:
            raise PrimitiveError(
                code=PRIM_NOT_FOUND,
                message=(
                    f"Unknown coordination strategy {strategy_name!r}. "
                    f"Available: {', '.join(sorted(_COORDINATION_STRATEGIES))}"
                ),
                details={
                    "primitive": "call-agent",
                    "step_id": context.current_step_id,
                    "strategy": strategy_name,
                },
            )

        strategy_config = coordination.get("config", {})
        strategy = strategy_cls(config=strategy_config or None)

        # --- Resolve agents ---
        agent_registry = context.deps.agent_registry
        if agent_registry is None:
            raise PrimitiveError(
                code=PRIM_NOT_FOUND,
                message="Missing required dependency 'agent_registry' for coordination",
                details={
                    "primitive": "call-agent",
                    "step_id": context.current_step_id,
                },
            )

        agent_names: list[str] = coordination.get("agents", [])
        agents: dict[str, Any] = {}
        for name in agent_names:
            if name not in agent_registry:
                raise PrimitiveError(
                    code=PRIM_NOT_FOUND,
                    message=f"Agent {name!r} not found in agent_registry",
                    details={
                        "primitive": "call-agent",
                        "step_id": context.current_step_id,
                        "agent_name": name,
                    },
                )
            agents[name] = agent_registry[name]

        # --- Build CoordinationTask ---
        prompt = coordination.get("prompt", config.get("prompt", ""))
        task = CoordinationTask(
            prompt=prompt,
            subtasks=coordination.get("subtasks", []),
            context_data=coordination.get("context_data", {}),
            timeout=coordination.get("timeout"),
        )

        # --- Execute coordination ---
        try:
            result = await strategy.coordinate(agents, task, context)
        except CoordinationError:
            raise
        except Exception as exc:
            raise PrimitiveError(
                code=PRIM_NOT_FOUND,
                message=f"Coordination failed: {exc}",
                details={
                    "primitive": "call-agent",
                    "step_id": context.current_step_id,
                    "strategy": strategy_name,
                },
            ) from exc

        return asdict(result)

    @staticmethod
    def _validate_config(config: dict[str, Any], context: ExecutionContext) -> None:
        """Validate required config keys.

        Args:
            config: Primitive configuration dict.
            context: Execution context for error details.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-201`` if ``workflow`` key is
                missing from config.
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
