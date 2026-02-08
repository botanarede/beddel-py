"""LLM primitive — Single-turn LLM call via ILLMProvider (blocking & streaming)."""

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
    from collections.abc import AsyncIterator

    from beddel.domain.ports import ILLMProvider

logger = logging.getLogger("beddel.primitives.llm")


def _build_request(config: dict[str, Any]) -> LLMRequest:
    """Build an LLMRequest from a resolved config dict.

    Extracts model, messages, temperature, max_tokens, response_format.
    Handles the ``system`` shorthand by prepending a system message.
    """
    messages: list[Message] = []

    # System shorthand: prepend system message
    if "system" in config:
        messages.append(Message(role="system", content=config["system"]))

    # Convert raw message dicts to Message instances
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
    if "stream" in config:
        kwargs["stream"] = config["stream"]

    return LLMRequest(**kwargs)


async def llm_primitive(
    config: dict[str, Any],
    context: ExecutionContext,
) -> LLMResponse | AsyncIterator[str]:
    """Execute a single-turn LLM call through the ILLMProvider port.

    When ``config["stream"]`` is ``True``, calls ``provider.stream()`` and
    returns an ``AsyncIterator[str]``.  Otherwise calls ``provider.complete()``
    and returns an ``LLMResponse``.
    """
    # Extract provider from context metadata
    provider: ILLMProvider | None = context.metadata.get("llm_provider")
    if provider is None:
        raise PrimitiveError(
            "llm_provider not found in execution context metadata",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "llm", "hint": "Inject ILLMProvider via metadata"},
        )

    request = _build_request(config)
    logger.debug(
        "LLM request: model=%s messages=%d stream=%s",
        request.model, len(request.messages), request.stream,
    )

    # Streaming path
    if request.stream:
        try:
            return await provider.stream(request)
        except Exception as exc:
            raise ProviderError(
                f"LLM provider stream failed: {exc}",
                code=ErrorCode.PROVIDER_ERROR,
                details={"primitive": "llm", "model": request.model, "stream": True},
            ) from exc

    # Blocking path
    try:
        response = await provider.complete(request)
    except Exception as exc:
        raise ProviderError(
            f"LLM provider call failed: {exc}",
            code=ErrorCode.PROVIDER_ERROR,
            details={"primitive": "llm", "model": request.model},
        ) from exc

    logger.debug("LLM response: tokens=%d", response.usage.total_tokens)
    return response
