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

from beddel.domain.models import ExecutionContext
from beddel.domain.ports import ILLMProvider, IPrimitive
from beddel.primitives._llm_utils import build_kwargs, get_model, get_provider

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
        return get_provider(context, "chat")

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
        return get_model(config, context, "chat")

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
           via :func:`_estimate_tokens` and drop the oldest non-system
           messages until the total is within budget.

        Tool-call pair preservation:
            Tool-call assistant messages (those containing a ``tool_calls``
            key) and their corresponding tool-response messages (``role:
            "tool"`` with a matching ``tool_call_id``) are treated as atomic
            units.  Dropping one side of a pair automatically drops the other
            to prevent invalid message sequences that LLM providers would
            reject with a 400 error.  This applies to both count-based and
            token-based trimming.

        System messages are never dropped — they define the conversation
        persona and are always placed first in the output.

        FIFO trimming:
            When the token budget is exceeded, the oldest non-system messages
            are dropped first (first-in, first-out).  This means early
            conversation context is lost before recent messages.  For
            long-running conversations, consumers should consider
            application-layer summarization — e.g., periodically condensing
            older messages into a single summary message — to preserve
            important context that would otherwise be silently dropped.

        Token estimation:
            Each message's token cost is estimated as
            ``max(1, len(content) // 4) + 4``:

            * The ``// 4`` divisor approximates the "1 token ≈ 4 characters"
              heuristic.  Actual counts vary by model and tokenizer.
            * ``max(1, ...)`` ensures every message contributes at least 1
              content token, preventing short or empty messages from being
              invisible to the budget.
            * The ``+ 4`` adds per-message framing overhead (~4 tokens for
              role, delimiters, and special tokens common across most LLM
              tokenizers).

            A future ``ITokenCounter`` port will allow injecting a precise,
            model-specific tokenizer instead of this heuristic, enabling
            accurate per-model token counting.

        Args:
            messages: Full message list including system and non-system messages.
            max_messages: Maximum number of non-system messages to retain.
                Defaults to ``50``.  ``None`` disables the count limit.
            max_context_tokens: Maximum estimated token budget for all messages.
                Defaults to ``None`` (unlimited).  Uses
                ``max(1, len(content) // 4) + 4`` as the per-message token
                estimate.

        Returns:
            A trimmed message list with system messages first, followed by
            the most recent non-system messages that fit within limits.
        """
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system_msgs = [m for m in messages if m.get("role") != "system"]

        # Step 1: Apply max_messages count limit (pair-aware).
        if max_messages is not None and len(non_system_msgs) > max_messages:
            non_system_msgs = non_system_msgs[-max_messages:]

            # Drop orphaned tool responses at the start of the retained list.
            # If the trim boundary split a tool-call pair, the first retained
            # message(s) may be tool responses whose assistant is gone.
            while non_system_msgs and non_system_msgs[0].get("role") == "tool":
                non_system_msgs.pop(0)

            # Drop orphaned assistant tool_calls at the end of the retained
            # list.  If the slice kept an assistant with tool_calls but its
            # tool responses were trimmed away, remove the assistant (and any
            # trailing orphaned tool messages from the same call).
            while (
                non_system_msgs
                and non_system_msgs[-1].get("role") == "assistant"
                and _collect_tool_call_ids(non_system_msgs[-1])
            ):
                assistant = non_system_msgs.pop()
                ids = _collect_tool_call_ids(assistant)
                while (
                    non_system_msgs
                    and non_system_msgs[-1].get("role") == "tool"
                    and non_system_msgs[-1].get("tool_call_id") in ids
                ):
                    non_system_msgs.pop()

        # Step 2: Apply max_context_tokens budget (pair-aware).
        if max_context_tokens is not None:
            system_tokens = sum(_estimate_tokens(m.get("content", "")) for m in system_msgs)
            budget = max_context_tokens - system_tokens

            if budget <= 0:
                non_system_msgs = []
            else:
                total = sum(_estimate_tokens(m.get("content", "")) for m in non_system_msgs)
                while non_system_msgs and total > budget:
                    removed = non_system_msgs.pop(0)
                    total -= _estimate_tokens(removed.get("content", ""))

                    if removed.get("role") == "assistant" and removed.get("tool_calls"):
                        # Dropped an assistant with tool_calls — also drop
                        # all corresponding tool-response messages.
                        ids_to_drop = _collect_tool_call_ids(removed)
                        if ids_to_drop:
                            kept: list[dict[str, Any]] = []
                            for m in non_system_msgs:
                                if (
                                    m.get("role") == "tool"
                                    and m.get("tool_call_id") in ids_to_drop
                                ):
                                    total -= _estimate_tokens(m.get("content", ""))
                                else:
                                    kept.append(m)
                            non_system_msgs = kept

                    elif removed.get("role") == "tool":
                        # Dropped a tool response — also drop the paired
                        # assistant and all sibling tool responses.
                        removed_tc_id = removed.get("tool_call_id")
                        if removed_tc_id:
                            # Find the paired assistant's full set of IDs.
                            all_ids: set[str] = set()
                            for m in non_system_msgs:
                                if m.get("role") == "assistant":
                                    m_ids = _collect_tool_call_ids(m)
                                    if removed_tc_id in m_ids:
                                        all_ids = m_ids
                                        break

                            if all_ids:
                                kept = []
                                for m in non_system_msgs:
                                    if (
                                        m.get("role") == "assistant"
                                        and _collect_tool_call_ids(m) == all_ids
                                    ) or (
                                        m.get("role") == "tool"
                                        and m.get("tool_call_id") in all_ids
                                    ):
                                        total -= _estimate_tokens(m.get("content", ""))
                                    else:
                                        kept.append(m)
                                non_system_msgs = kept

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
        return build_kwargs(config)


def _estimate_tokens(content: str) -> int:
    """Estimate the token count for a message's content.

    Uses a heuristic of ~4 characters per token with a minimum of 1 content
    token, plus 4 tokens of per-message framing overhead (role, delimiters).

    Args:
        content: The message content string.

    Returns:
        Estimated token count (always >= 5).
    """
    return max(1, len(content or "") // 4) + 4


def _collect_tool_call_ids(message: dict[str, Any]) -> set[str]:
    """Extract tool_call IDs from an assistant message's ``tool_calls`` list.

    Args:
        message: A message dict that may contain a ``tool_calls`` key.

    Returns:
        A set of tool_call ID strings.  Empty if the message has no
        ``tool_calls`` or is not an assistant message.
    """
    tool_calls = message.get("tool_calls")
    if not tool_calls:
        return set()
    return {tc["id"] for tc in tool_calls if "id" in tc}
