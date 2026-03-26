"""LLM primitive — single-turn LLM invocation for Beddel workflows.

Provides :class:`LLMPrimitive`, which implements :class:`~beddel.domain.ports.IPrimitive`
and delegates to an :class:`~beddel.domain.ports.ILLMProvider` instance read from
``context.deps.llm_provider``.

Supports both synchronous (request/response) and streaming modes.
"""

from __future__ import annotations

from typing import Any

from beddel.domain.models import ExecutionContext
from beddel.domain.ports import ILLMProvider, IPrimitive
from beddel.primitives._llm_utils import build_kwargs, get_model, get_provider
from beddel.primitives._tool_use import run_tool_use_loop

__all__ = [
    "LLMPrimitive",
]


class LLMPrimitive(IPrimitive):
    """Single-turn LLM invocation primitive.

    Reads the LLM provider from ``context.deps.llm_provider`` and
    forwards the call with model, messages, and optional parameters.

    Config keys:
        model (str): Required. Model identifier (e.g. ``"gpt-4o"``).
        prompt (str): A user prompt — mutually exclusive with ``messages``.
        messages (list[dict]): Chat-style message list — mutually exclusive
            with ``prompt``.
        temperature (float): Optional sampling temperature.
        max_tokens (int): Optional maximum tokens to generate.
        stream (bool): If ``True``, return an async generator of chunks
            instead of a complete response dict.

    Example config::

        {
            "model": "gpt-4o",
            "prompt": "Hello, world!",
            "temperature": 0.7,
            "max_tokens": 100,
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute a single-turn LLM invocation.

        Args:
            config: Primitive configuration containing ``model`` (required)
                and either ``prompt`` or ``messages``, plus optional
                ``temperature``, ``max_tokens``, and ``stream``.
            context: Execution context — must contain an
                :class:`~beddel.domain.ports.ILLMProvider` instance at
                ``context.deps.llm_provider``.

        Returns:
            When ``stream`` is ``False`` (default): the provider's response
            dict (contains at minimum a ``"content"`` key).
            When ``stream`` is ``True``: a dict with a ``"stream"`` key
            holding an async generator that yields string chunks.

            Streaming consumption notes:

            - The async generator may raise
              ``~beddel.adapters.errors.AdapterError`` during
              iteration (network failures, provider timeouts,
              rate limits). Consumers should handle this.
            - Use ``contextlib.aclosing()`` for proper cleanup::

                  async with contextlib.aclosing(
                      result["stream"]
                  ) as stream:
                      async for chunk in stream:
                          process(chunk)

            - Unconsumed or partially consumed generators may
              leak underlying provider connections. Always
              exhaust the generator or wrap with ``aclosing()``.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-003`` if ``llm_provider`` is
                missing from ``context.deps``.
            PrimitiveError: ``BEDDEL-PRIM-004`` if required config key
                ``model`` is missing.
        """
        provider = self._get_provider(context)
        model = self._get_model(config, context)
        messages = self._build_messages(config)
        kwargs = self._build_kwargs(config)

        if config.get("stream"):
            return {"stream": provider.stream(model, messages, **kwargs)}

        tool_schemas = config.get("tool_schemas")
        if tool_schemas:
            tool_registry = context.deps.tool_registry
            if tool_registry is None:
                tool_registry = {}
            return await run_tool_use_loop(
                provider,
                model,
                messages,
                tool_schemas,
                tool_registry,
                context,
                max_iterations=config.get("max_tool_iterations", 10),
                allowed_tools=context.metadata.get("_workflow_allowed_tools"),
                provider_kwargs=kwargs,
            )

        return await provider.complete(model, messages, **kwargs)

    def _get_provider(self, context: ExecutionContext) -> ILLMProvider:
        """Extract and validate the LLM provider from context deps.

        Args:
            context: The current execution context.

        Returns:
            The :class:`ILLMProvider` instance.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-003`` if ``llm_provider`` is
                missing from deps or does not implement :class:`ILLMProvider`.
        """
        return get_provider(context, "llm")

    def _get_model(self, config: dict[str, Any], context: ExecutionContext) -> str:
        """Extract and validate the model identifier from config.

        Args:
            config: Primitive configuration dict.
            context: The current execution context (for error details).

        Returns:
            The model identifier string.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-004`` if ``model`` is missing.
        """
        return get_model(config, context, "llm")

    @staticmethod
    def _build_messages(config: dict[str, Any]) -> list[dict[str, Any]]:
        """Build the messages list from config.

        If ``prompt`` is provided, wraps it as a single user message.
        If ``messages`` is provided, passes through directly.
        Falls back to an empty list if neither is present.

        Args:
            config: Primitive configuration dict.

        Returns:
            A list of message dicts suitable for the LLM provider.
        """
        if "prompt" in config:
            return [{"role": "user", "content": config["prompt"]}]
        if "messages" in config:
            return config["messages"]
        return []

    @staticmethod
    def _build_kwargs(config: dict[str, Any]) -> dict[str, Any]:
        """Extract optional provider kwargs from config.

        Picks ``temperature`` and ``max_tokens`` if present.

        Args:
            config: Primitive configuration dict.

        Returns:
            A dict of keyword arguments to forward to the provider.
        """
        return build_kwargs(config)
