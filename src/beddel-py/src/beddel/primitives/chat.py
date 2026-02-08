"""Chat primitive — Multi-turn conversational LLM call via ILLMProvider."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    LLMRequest,
    LLMResponse,
    Message,
    PrimitiveError,
    ProviderError,
)

if TYPE_CHECKING:
    from beddel.domain.ports import ILLMProvider

logger = logging.getLogger("beddel.primitives.chat")


def _build_chat_request(config: dict[str, Any]) -> LLMRequest:
    """Build an LLMRequest from a resolved config dict with history support.

    Message assembly order:
    1. System message (from ``system`` shorthand, if present)
    2. History messages (from ``history`` field, if present)
    3. New messages (from ``messages`` field)
    """
    messages: list[Message] = []

    # 1. System shorthand: prepend system message
    if "system" in config:
        messages.append(Message(role="system", content=config["system"]))

    # 2. History: insert historical messages after system, before new messages
    for msg in config.get("history", []):
        messages.append(Message(role=msg["role"], content=msg["content"]))

    # 3. New messages from config
    for msg in config.get("messages", []):
        messages.append(Message(role=msg["role"], content=msg["content"]))

    kwargs: dict[str, Any] = {
        "model": config["model"],
        "messages": messages,
    }
    if "temperature" in config:
        kwargs["temperature"] = config["temperature"]
    if "max_tokens" in config:
        kwargs["max_tokens"] = config["max_tokens"]
    if "response_format" in config:
        kwargs["response_format"] = config["response_format"]

    return LLMRequest(**kwargs)


async def chat_primitive(
    config: dict[str, Any],
    context: ExecutionContext,
) -> LLMResponse:
    """Execute a multi-turn conversational LLM call through the ILLMProvider port.

    Supports ``history`` field for incorporating previous conversation turns,
    and ``system`` shorthand for prepending a system message.
    """
    # Extract provider from context metadata
    provider: ILLMProvider | None = context.metadata.get("llm_provider")
    if provider is None:
        raise PrimitiveError(
            "llm_provider not found in execution context metadata",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "chat", "hint": "Inject ILLMProvider via metadata"},
        )

    request = _build_chat_request(config)
    logger.debug(
        "Chat request: model=%s messages=%d",
        request.model,
        len(request.messages),
    )

    try:
        response = await provider.complete(request)
    except Exception as exc:
        raise ProviderError(
            f"Chat provider call failed: {exc}",
            code=ErrorCode.PROVIDER_ERROR,
            details={"primitive": "chat", "model": request.model},
        ) from exc

    logger.debug("Chat response: tokens=%d", response.usage.total_tokens)
    return response
