"""Agent delegation execution strategy for Beddel workflows.

Translates a workflow definition into a contextualized prompt and delegates
execution to an external agent backend resolved from the agent registry.
This generalises the Codex-specific pattern into a backend-agnostic strategy
that works with any :class:`~beddel.domain.ports.IAgentAdapter` implementation.

Only the ``auto`` approval policy is supported in Epic 3.2.  Requesting
``manual`` or ``supervised`` raises
:class:`~beddel.domain.errors.AgentError` with code ``BEDDEL-AGENT-708``.
"""

from __future__ import annotations

import logging
from typing import Any

from beddel.domain.errors import AgentError
from beddel.domain.models import ExecutionContext, Workflow
from beddel.domain.ports import StepRunner
from beddel.error_codes import (
    AGENT_ADAPTER_NOT_FOUND,
    AGENT_APPROVAL_NOT_IMPLEMENTED,
    AGENT_DELEGATION_FAILED,
    AGENT_NOT_CONFIGURED,
)

_log = logging.getLogger(__name__)

_STEP_ID = "agent-delegation"
"""Synthetic step id used for lifecycle hooks and step_results."""


class AgentDelegationStrategy:
    """Execution strategy that delegates an entire workflow to an agent adapter.

    Instead of iterating steps sequentially, this strategy builds a single
    prompt from the workflow definition and context inputs, then delegates
    execution to an :class:`~beddel.domain.ports.IAgentAdapter` resolved
    by name from ``context.deps.agent_registry``.

    The strategy satisfies :class:`~beddel.domain.ports.IExecutionStrategy`
    via structural subtyping (Protocol conformance).

    Configuration is merged from two sources (constructor config as base,
    workflow ``metadata.execution_strategy`` as override):

    - ``adapter`` (str): Name of the agent adapter in the registry.
    - ``model`` (str | None): Optional model override for the adapter.
    - ``sandbox`` (str): Sandbox access level (default ``"read-only"``).
    - ``approval_policy`` (str): ``"auto"`` (default), ``"manual"``, or
      ``"supervised"``.  Only ``"auto"`` is implemented in Epic 3.2.

    Args:
        config: Optional base configuration dict.  Keys from
            ``workflow.metadata["execution_strategy"]`` override these
            at execution time.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialise the strategy with optional base configuration.

        Args:
            config: Optional base configuration dict.  Workflow-level
                metadata overrides these values at execution time.
        """
        self._config: dict[str, Any] = config or {}

    async def execute(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        step_runner: StepRunner,
    ) -> None:
        """Delegate the workflow to an external agent adapter.

        Merges constructor config with ``workflow.metadata.execution_strategy``,
        validates the approval policy, resolves the adapter from the agent
        registry, builds a prompt, and delegates execution.  Results are
        stored in ``context.step_results["agent-delegation"]``.

        Lifecycle hooks (``on_step_start``, ``on_step_end``, ``on_error``)
        are fired around the delegation call when a hook manager is
        available.

        Args:
            workflow: The workflow definition to delegate.
            context: Mutable runtime context carrying inputs, step results,
                and the dependency container with the agent registry.
            step_runner: Step-runner callback (unused by this strategy but
                required by the ``IExecutionStrategy`` protocol).

        Raises:
            AgentError: With code ``BEDDEL-AGENT-708`` if the approval
                policy is ``"manual"`` or ``"supervised"``.
            AgentError: With code ``BEDDEL-AGENT-706`` if no adapter name
                is specified or the named adapter is not in the registry.
            AgentError: With code ``BEDDEL-AGENT-700`` if the agent
                registry is not configured.
            AgentError: With code ``BEDDEL-AGENT-707`` if the adapter
                execution fails.
        """
        # 1. Merge config: constructor base + workflow metadata override
        config: dict[str, Any] = {
            **self._config,
            **workflow.metadata.get("execution_strategy", {}),
        }

        # 2. Validate approval policy
        policy = config.get("approval_policy", "auto")
        if policy in ("manual", "supervised"):
            raise AgentError(
                AGENT_APPROVAL_NOT_IMPLEMENTED,
                f"Approval policy '{policy}' is not yet implemented. "
                "Only 'auto' is supported in Epic 3.2.",
            )

        # 3. Extract adapter name
        adapter_name: str | None = config.get("adapter")
        if not adapter_name:
            raise AgentError(
                AGENT_ADAPTER_NOT_FOUND,
                "No adapter name specified in agent-delegation strategy config",
            )

        # 4. Get agent registry
        registry = context.deps.agent_registry
        if registry is None:
            raise AgentError(
                AGENT_NOT_CONFIGURED,
                "agent_registry not configured in execution dependencies",
            )

        # 5. Resolve adapter by name
        adapter = registry.get(adapter_name)
        if adapter is None:
            raise AgentError(
                AGENT_ADAPTER_NOT_FOUND,
                f"Agent adapter '{adapter_name}' not found in agent_registry",
            )

        # 6. Check suspended before delegation
        if context.suspended:
            return

        hooks = context.deps.lifecycle_hooks

        # 7. Fire on_step_start (non-critical side effect)
        if hooks is not None:
            try:
                await hooks.on_step_start(_STEP_ID, _STEP_ID)
            except Exception:
                _log.warning("on_step_start hook failed", exc_info=True)

        # 8. Build prompt
        prompt = self._build_prompt(workflow, context)

        # 9. Delegate to adapter
        try:
            result = await adapter.execute(
                prompt,
                model=config.get("model"),
                sandbox=config.get("sandbox", "read-only"),
            )
        except AgentError:
            raise
        except Exception as exc:
            # Fire on_error (non-critical), then wrap in AgentError
            if hooks is not None:
                try:
                    await hooks.on_error(_STEP_ID, exc)
                except Exception:
                    _log.warning("on_error hook failed", exc_info=True)
            raise AgentError(
                AGENT_DELEGATION_FAILED,
                f"Agent delegation failed: {exc}",
                details={
                    "step_id": _STEP_ID,
                    "primitive_type": _STEP_ID,
                    "original_error": str(exc),
                },
            ) from exc

        # 10. Populate step_results
        step_result: dict[str, Any] = {
            "output": result.output,
            "files_changed": result.files_changed,
            "usage": result.usage,
        }
        context.step_results[_STEP_ID] = step_result

        # 11. Fire on_step_end (non-critical side effect)
        if hooks is not None:
            try:
                await hooks.on_step_end(_STEP_ID, step_result)
            except Exception:
                _log.warning("on_step_end hook failed", exc_info=True)

    def _build_prompt(self, workflow: Workflow, context: ExecutionContext) -> str:
        """Build a contextualized prompt from the workflow and inputs.

        Translates the workflow definition into a structured text prompt
        that an agent can execute.  Each step is listed with its id,
        primitive type, and configuration.

        Args:
            workflow: The workflow definition containing steps and metadata.
            context: The execution context carrying input variables.

        Returns:
            A formatted prompt string ready for agent delegation.
        """
        lines: list[str] = [
            "You are executing a Beddel workflow.",
            "",
            f"Workflow: {workflow.name}",
            f"Description: {workflow.description}",
        ]

        if workflow.input_schema:
            lines.append("")
            lines.append("Input schema:")
            for key, spec in workflow.input_schema.items():
                lines.append(f"  {key}: {spec}")

        lines.append("")
        lines.append("Steps:")

        for idx, step in enumerate(workflow.steps, start=1):
            config_repr = ", ".join(f"{k}: {v}" for k, v in step.config.items())
            lines.append(f"{idx}. {step.id} [{step.primitive}]: {config_repr}")

        lines.append("")
        lines.append("Input variables:")
        for key, value in context.inputs.items():
            lines.append(f"  {key}: {value}")

        lines.append("")
        lines.append(
            "Execute each step in order. Return output text, "
            "a list of files changed, and token usage."
        )

        return "\n".join(lines)
