"""Chat primitive — multi-turn LLM invocation with context windowing for Beddel workflows.

Provides :class:`ChatPrimitive`, which implements :class:`~beddel.domain.ports.IPrimitive`
and delegates to an :class:`~beddel.domain.ports.ILLMProvider` instance read from
``context.deps.llm_provider``.

Unlike the single-turn :class:`~beddel.primitives.llm.LLMPrimitive`, the chat
primitive manages conversation history with role-based messages and applies
context windowing to keep the message list within configurable limits.

Supports both synchronous (request/response) and streaming modes.
"""

from __future__ import annotations

from typing import Any

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import ILLMProvider, IPrimitive

__all__ = [
    "ChatPrimitive",
]


class ChatPrimitive(IPrimitive):
    """Multi-turn chat primitive with context windowing.

    Reads the LLM provider from ``context.deps.llm_provider`` and
    forwards the call with model, messages (after context windowing),
    and optional parameters.

    Config keys:
        model (str): Required. Model identifier (e.g. ``"gpt-4o"``).
        messages (list[dict]): Conversation history as role-based message
            dicts (``{role, content}``).
        system (str): Optional system message — prepended to the messages
            list if provided.
        max_messages (int): Maximum number of non-system messages to retain
            (default: ``50``).
        max_context_tokens (int): Estimated token budget for the context
            window (default: ``None`` = unlimited).
        temperature (float): Optional sampling temperature.
        max_tokens (int): Optional maximum tokens to generate (response limit).
        stream (bool): If ``True``, return an async generator of chunks
            instead of a complete response dict.

    Example config::

        {
            "model": "gpt-4o",
            "system": "You are a helpful assistant.",
            "messages": [
                {"role": "user", "content": "Hello!"},
                {"role": "assistant", "content": "Hi there!"},
                {"role": "user", "content": "How are you?"},
            ],
            "max_messages": 20,
            "temperature": 0.7,
        }
    """

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute a multi-turn chat invocation with context windowing.

        Args:
            config: Primitive configuration containing ``model`` (required),
                ``messages`` and/or ``system``, plus optional
                ``max_messages``, ``max_context_tokens``, ``temperature``,
                ``max_tokens``, and ``stream``.
            context: Execution context — must contain an
                :class:`~beddel.domain.ports.ILLMProvider` instance at
                ``context.deps.llm_provider``.

        Returns:
            When ``stream`` is ``False`` (default): the provider's response
            dict (contains at minimum a ``"content"`` key).
            When ``stream`` is ``True``: a dict with a ``"stream"`` key
            holding an async generator that yields string chunks.

        Raises:
            PrimitiveError: ``BEDDEL-PRIM-003`` if ``llm_provider`` is
                missing from ``context.deps``.
            PrimitiveError: ``BEDDEL-PRIM-004`` if required config key
                ``model`` is missing.
        """
        provider = self._get_provider(context)
        model = self._get_model(config, context)
        messages = self._build_messages(config)
        messages = self._apply_context_window(
            messages,
            max_messages=config.get("max_messages", 50),
            max_context_tokens=config.get("max_context_tokens"),
        )
        kwargs = self._build_kwargs(config)

        if config.get("stream"):
            return {"stream": provider.stream(model, messages, **kwargs)}

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
        provider = context.deps.llm_provider
        if provider is None:
            raise PrimitiveError(
                "BEDDEL-PRIM-003",
                "Missing 'llm_provider' in execution context deps",
                {
                    "step_id": context.current_step_id,
                    "primitive_type": "chat",
                },
            )
        if not isinstance(provider, ILLMProvider):
            raise PrimitiveError(
                "BEDDEL-PRIM-003",
                "llm_provider in context.deps does not implement ILLMProvider",
                {
                    "step_id": context.current_step_id,
                    "primitive_type": "chat",
                    "provider_type": type(provider).__name__,
                },
            )
        return provider

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
        model = config.get("model")
        if model is None:
            raise PrimitiveError(
                "BEDDEL-PRIM-004",
                "Missing required config key: 'model'",
                {
                    "step_id": context.current_step_id,
                    "primitive_type": "chat",
                    "missing_key": "model",
                },
            )
        return model

    @staticmethod
    def _build_messages(config: dict[str, Any]) -> list[dict[str, Any]]:
        """Build the messages list from config, prepending system message if provided.

        If ``system`` is present in config, a system-role message is prepended
        to the messages list.  The ``messages`` key provides the conversation
        history; defaults to an empty list if absent.

        Args:
            config: Primitive configuration dict.

        Returns:
            A list of message dicts suitable for the LLM provider.
        """
        messages: list[dict[str, Any]] = list(config.get("messages", []))
        if "system" in config:
            messages.insert(0, {"role": "system", "content": config["system"]})
        return messages

    @staticmethod
    def _apply_context_window(
        messages: list[dict[str, Any]],
        max_messages: int | None = 50,
        max_context_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """Trim conversation history to fit within context window limits.

        Applies two sequential filters to non-system messages while always
        preserving system messages:

        1. If ``max_messages`` is set and the non-system message count exceeds
           it, keep only the last ``max_messages`` non-system messages.
        2. If ``max_context_tokens`` is set, estimate tokens per message
           (``len(content) // 4``) and drop the oldest non-system messages
           until the total is within budget.

        System messages are never dropped — they define the conversation
        persona and are always placed first in the output.

        Args:
            messages: Full message list including system and non-system messages.
            max_messages: Maximum number of non-system messages to retain.
                Defaults to ``50``.  ``None`` disables the count limit.
            max_context_tokens: Maximum estimated token budget for all messages.
                Defaults to ``None`` (unlimited).  Uses ``len(content) // 4``
                as the per-message token estimate.

        Returns:
            A trimmed message list with system messages first, followed by
            the most recent non-system messages that fit within limits.
        """
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system_msgs = [m for m in messages if m.get("role") != "system"]

        # Step 1: Apply max_messages count limit.
        if max_messages is not None and len(non_system_msgs) > max_messages:
            non_system_msgs = non_system_msgs[-max_messages:]

        # Step 2: Apply max_context_tokens budget.
        if max_context_tokens is not None:
            # Calculate system message token cost (always included).
            system_tokens = sum(len(m.get("content", "")) // 4 for m in system_msgs)
            budget = max_context_tokens - system_tokens

            # Guard: if budget is non-positive, no non-system messages can fit.
            if budget <= 0:
                non_system_msgs = []
            else:
                # O(n) trimming: compute total once, subtract as we drop.
                total = sum(len(m.get("content", "")) // 4 for m in non_system_msgs)
                while non_system_msgs and total > budget:
                    removed = non_system_msgs.pop(0)
                    total -= len(removed.get("content", "")) // 4

        return system_msgs + non_system_msgs

    @staticmethod
    def _build_kwargs(config: dict[str, Any]) -> dict[str, Any]:
        """Extract optional provider kwargs from config.

        Picks ``temperature`` and ``max_tokens`` if present.

        Args:
            config: Primitive configuration dict.

        Returns:
            A dict of keyword arguments to forward to the provider.
        """
        kwargs: dict[str, Any] = {}
        if "temperature" in config:
            kwargs["temperature"] = config["temperature"]
        if "max_tokens" in config:
            kwargs["max_tokens"] = config["max_tokens"]
        return kwargs
