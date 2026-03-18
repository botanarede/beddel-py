"""Agent-exec primitive — external agent delegation for Beddel workflows.

Provides :class:`AgentExecPrimitive`, which implements
:class:`~beddel.domain.ports.IPrimitive` and enables workflows to delegate
individual steps to external agent backends via the
:class:`~beddel.domain.ports.IAgentAdapter` port.
"""

from __future__ import annotations

from typing import Any

from beddel.domain.errors import AgentError
from beddel.domain.models import AgentResult, ExecutionContext
from beddel.domain.ports import IAgentAdapter, IPrimitive
from beddel.domain.resolver import VariableResolver
from beddel.error_codes import (
    AGENT_ADAPTER_NOT_FOUND,
    AGENT_EXECUTION_FAILED,
    AGENT_MISSING_ADAPTER,
    AGENT_MISSING_PROMPT,
    AGENT_NOT_CONFIGURED,
)

__all__ = [
    "AgentExecPrimitive",
]


class AgentExecPrimitive(IPrimitive):
    """Agent delegation primitive.

    Looks up an agent adapter by name from ``context.deps.agent_registry``,
    resolves the prompt via :class:`VariableResolver`, invokes the adapter,
    and returns a structured result dict with ``output``, ``files_changed``,
    and ``usage`` fields.

    Config keys:
        adapter (str): Required. Agent adapter name to look up in the registry.
        prompt (str): Required. Instruction to send to the agent. Supports
            ``$input`` and ``$stepResult`` variable references.
        model (str): Optional. Model override for the agent backend.
        sandbox (str): Optional. Sandbox access level. Defaults to
            ``"read-only"``. One of ``"read-only"``, ``"workspace-write"``,
            or ``"danger-full-access"``.
        tools (list[str]): Optional. Tool names the agent is allowed to use.
        output_schema (dict): Optional. JSON Schema for structured output.

    Example config::

        {
            "adapter": "codex",
            "prompt": "Review $input.code for security issues",
            "model": "o3-mini",
            "sandbox": "read-only",
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the agent-exec primitive.

        Validates config, extracts the agent registry, resolves the adapter
        by name, resolves the prompt, invokes the adapter, and returns a
        structured result dict.

        Args:
            config: Primitive configuration containing ``adapter`` and
                ``prompt`` (required), plus optional ``model``, ``sandbox``,
                ``tools``, and ``output_schema``.
            context: Execution context providing runtime data and dependencies.

        Returns:
            A dict with ``output`` (str), ``files_changed`` (list[str]),
            and ``usage`` (dict).

        Raises:
            AgentError: ``BEDDEL-AGENT-704`` if ``adapter`` key is missing.
            AgentError: ``BEDDEL-AGENT-705`` if ``prompt`` key is missing.
            AgentError: ``BEDDEL-AGENT-700`` if agent_registry is not configured.
            AgentError: ``BEDDEL-AGENT-706`` if adapter not found in registry.
            AgentError: ``BEDDEL-AGENT-701`` if adapter execution fails.
        """
        self._validate_config(config, context)
        registry = self._get_agent_registry(context)
        adapter_name: str = config["adapter"]
        adapter = self._resolve_adapter(adapter_name, registry, context)

        resolver = VariableResolver()
        prompt: str = resolver.resolve(config["prompt"], context)

        agent_result = await self._invoke_adapter(
            adapter,
            prompt,
            model=config.get("model"),
            sandbox=config.get("sandbox", "read-only"),
            tools=config.get("tools"),
            output_schema=config.get("output_schema"),
        )

        return {
            "output": agent_result.output,
            "files_changed": agent_result.files_changed,
            "usage": agent_result.usage,
        }

    @staticmethod
    def _validate_config(config: dict[str, Any], context: ExecutionContext) -> None:
        """Validate required config keys.

        Args:
            config: Primitive configuration dict.
            context: Execution context for error details.

        Raises:
            AgentError: ``BEDDEL-AGENT-704`` if ``adapter`` key is missing.
            AgentError: ``BEDDEL-AGENT-705`` if ``prompt`` key is missing.
        """
        if "adapter" not in config:
            raise AgentError(
                code=AGENT_MISSING_ADAPTER,
                message="Missing required config key 'adapter' for agent-exec primitive",
                details={
                    "primitive": "agent-exec",
                    "step_id": context.current_step_id,
                },
            )
        if "prompt" not in config:
            raise AgentError(
                code=AGENT_MISSING_PROMPT,
                message="Missing required config key 'prompt' for agent-exec primitive",
                details={
                    "primitive": "agent-exec",
                    "step_id": context.current_step_id,
                },
            )

    @staticmethod
    def _get_agent_registry(
        context: ExecutionContext,
    ) -> dict[str, IAgentAdapter]:
        """Extract agent_registry from context deps.

        Args:
            context: Execution context providing dependencies.

        Returns:
            The agent registry mapping adapter names to IAgentAdapter instances.

        Raises:
            AgentError: ``BEDDEL-AGENT-700`` if agent_registry is not configured.
        """
        if context.deps.agent_registry is None:
            raise AgentError(
                code=AGENT_NOT_CONFIGURED,
                message="Missing required dependency 'agent_registry' for agent-exec primitive",
                details={
                    "primitive": "agent-exec",
                    "step_id": context.current_step_id,
                },
            )
        return context.deps.agent_registry

    @staticmethod
    def _resolve_adapter(
        name: str,
        registry: dict[str, IAgentAdapter],
        context: ExecutionContext,
    ) -> IAgentAdapter:
        """Look up an adapter by name in the registry.

        Args:
            name: Adapter name to look up.
            registry: Mapping of adapter names to IAgentAdapter instances.
            context: Execution context for error details.

        Returns:
            The IAgentAdapter instance.

        Raises:
            AgentError: ``BEDDEL-AGENT-706`` if adapter not found.
        """
        if name not in registry:
            raise AgentError(
                code=AGENT_ADAPTER_NOT_FOUND,
                message=f"Adapter '{name}' not found in agent_registry",
                details={
                    "primitive": "agent-exec",
                    "step_id": context.current_step_id,
                    "adapter": name,
                    "available_adapters": list(registry.keys()),
                },
            )
        return registry[name]

    @staticmethod
    async def _invoke_adapter(
        adapter: IAgentAdapter,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Invoke the agent adapter, wrapping non-AgentError exceptions.

        Args:
            adapter: The IAgentAdapter instance to invoke.
            prompt: Resolved prompt string.
            model: Optional model override.
            sandbox: Sandbox access level.
            tools: Optional tool names list.
            output_schema: Optional JSON Schema for structured output.

        Returns:
            The AgentResult from the adapter.

        Raises:
            AgentError: ``BEDDEL-AGENT-701`` if adapter execution fails
                with a non-AgentError exception.
        """
        try:
            return await adapter.execute(
                prompt,
                model=model,
                sandbox=sandbox,
                tools=tools,
                output_schema=output_schema,
            )
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(
                code=AGENT_EXECUTION_FAILED,
                message=f"Agent execution failed: {exc}",
                details={
                    "primitive": "agent-exec",
                    "original_error": str(exc),
                    "error_type": type(exc).__name__,
                },
            ) from exc
