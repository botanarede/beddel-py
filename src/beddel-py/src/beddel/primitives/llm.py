"""LLM primitive — Single-turn LLM call via ILLMProvider (blocking & streaming)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from beddel.adapters.structured import StructuredOutputHandler
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


def _build_request(
    config: dict[str, Any],
) -> tuple[LLMRequest, StructuredOutputHandler[Any] | None]:
    """Build an LLMRequest from a resolved config dict.

    Extracts model, messages, temperature, max_tokens, response_format.
    Handles the ``system`` shorthand by prepending a system message.

    When ``config["response_model"]`` is present, instantiates a
    :class:`StructuredOutputHandler` and sets ``response_format`` from
    ``handler.to_response_format()``.

    Returns:
        A tuple of ``(request, handler)`` where *handler* is ``None`` when
        no ``response_model`` was configured.
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
    if "stream" in config:
        kwargs["stream"] = config["stream"]

    # Structured output: response_model takes precedence over raw response_format
    handler: StructuredOutputHandler[Any] | None = None
    if "response_model" in config:
        handler = StructuredOutputHandler(config["response_model"])
        kwargs["response_format"] = handler.to_response_format()
        logger.debug(
            "Structured output enabled: model=%s response_model=%s",
            config["model"],
            config["response_model"].__name__,
        )
    elif "response_format" in config:
        kwargs["response_format"] = config["response_format"]

    return LLMRequest(**kwargs), handler


async def llm_primitive(
    config: dict[str, Any],
    context: ExecutionContext,
) -> LLMResponse | AsyncIterator[str] | dict[str, Any]:
    """Execute a single-turn LLM call through the ILLMProvider port.

    When ``config["stream"]`` is ``True``, calls ``provider.stream()`` and
    returns an ``AsyncIterator[str]``.  Otherwise calls ``provider.complete()``
    and returns an ``LLMResponse``.

    When ``config["response_model"]`` is set, the response is parsed and
    validated against the Pydantic model and returned as a dict via
    ``.model_dump()``.
    """
    # Extract provider from context metadata
    provider: ILLMProvider | None = context.metadata.get("llm_provider")
    if provider is None:
        raise PrimitiveError(
            "llm_provider not found in execution context metadata",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "llm", "hint": "Inject ILLMProvider via metadata"},
        )

    request, handler = _build_request(config)
    logger.debug(
        "LLM request: model=%s messages=%d stream=%s",
        request.model, len(request.messages), request.stream,
    )

    # Streaming path — structured output is blocking-only
    if request.stream:
        if handler is not None:
            raise PrimitiveError(
                "Structured output (response_model) is not supported with streaming",
                code=ErrorCode.EXEC_STEP_FAILED,
                details={
                    "primitive": "llm",
                    "model": request.model,
                    "hint": "Remove 'stream: true' or 'response_model' from config",
                },
            )
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

    # Structured output: parse and validate response against Pydantic model
    if handler is not None:
        instance = handler.parse_response(response.content)
        logger.debug(
            "Structured output parsed: model=%s",
            config["response_model"].__name__,
        )
        return instance.model_dump()

    return response
