"""LLM primitive — Single-turn blocking LLM call via ILLMProvider."""

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

    return LLMRequest(**kwargs)


async def llm_primitive(
    config: dict[str, Any],
    context: ExecutionContext,
) -> LLMResponse:
    """Execute a single-turn LLM call through the ILLMProvider port."""
    # Extract provider from context metadata
    provider: ILLMProvider | None = context.metadata.get("llm_provider")
    if provider is None:
        raise PrimitiveError(
            "llm_provider not found in execution context metadata",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "llm", "hint": "Inject ILLMProvider via metadata"},
        )

    request = _build_request(config)
    logger.debug("LLM request: model=%s messages=%d", request.model, len(request.messages))

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
