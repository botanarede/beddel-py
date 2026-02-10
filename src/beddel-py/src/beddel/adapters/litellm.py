"""LiteLLM adapter — Unified LLM provider via litellm.acompletion()."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import litellm

from beddel.domain.models import (
    ErrorCode,
    LLMResponse,
    ProviderError,
    TokenUsage,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from beddel.domain.models import LLMRequest

logger = logging.getLogger("beddel.adapters.litellm")


class LiteLLMAdapter:
    """Adapter bridging ``ILLMProvider`` to LiteLLM's unified API.

    Implements the ``ILLMProvider`` protocol via structural subtyping.

    Args:
        api_key: Optional API key passed through to every LiteLLM call.
        api_base: Optional base URL passed through to every LiteLLM call.
        extra_params: Optional provider-specific parameters merged into every
            ``litellm.acompletion()`` call (e.g. ``custom_llm_provider``,
            ``aws_region_name``).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base
        self.extra_params = extra_params

    def _build_params(self, request: LLMRequest) -> dict[str, Any]:
        """Map an ``LLMRequest`` to LiteLLM ``acompletion()`` kwargs.

        Converts ``Message`` objects to plain dicts and conditionally includes
        optional fields only when they are set.
        """
        params: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": msg.role, "content": msg.content} for msg in request.messages
            ],
            "temperature": request.temperature,
        }

        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens

        if request.response_format is not None:
            params["response_format"] = request.response_format

        if self.api_key is not None:
            params["api_key"] = self.api_key

        if self.api_base is not None:
            params["api_base"] = self.api_base

        if self.extra_params:
            params.update(self.extra_params)

        return params

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Execute a single LLM completion request via ``litellm.acompletion()``.

        Maps the LiteLLM response back to a domain ``LLMResponse``.
        """
        params = self._build_params(request)
        logger.debug("LiteLLM complete: model=%s messages=%d", request.model, len(request.messages))

        try:
            response = await litellm.acompletion(**params)
        except Exception as exc:
            logger.debug("LiteLLM complete failed: model=%s error=%s", request.model, exc)
            raise ProviderError(
                f"LiteLLM completion failed: {exc}",
                code=ErrorCode.PROVIDER_ERROR,
                details={"adapter": "litellm", "model": request.model},
            ) from exc

        choice = response.choices[0]
        usage = response.usage or litellm.Usage(
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
        )

        logger.debug(
            "LiteLLM complete ok: model=%s tokens=%d",
            response.model,
            usage.total_tokens,
        )

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model or request.model,
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            ),
            finish_reason=choice.finish_reason or "stop",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Stream LLM completion chunks via ``litellm.acompletion(stream=True)``.

        Yields content strings as they arrive from the provider.
        """
        params = self._build_params(request)
        params["stream"] = True
        logger.debug("LiteLLM stream: model=%s messages=%d", request.model, len(request.messages))

        try:
            response = await litellm.acompletion(**params)
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta.content is not None:
                    yield delta.content
        except ProviderError:
            raise
        except Exception as exc:
            logger.debug("LiteLLM stream failed: model=%s error=%s", request.model, exc)
            raise ProviderError(
                f"LiteLLM stream failed: {exc}",
                code=ErrorCode.PROVIDER_ERROR,
                details={"adapter": "litellm", "model": request.model, "stream": True},
            ) from exc

        logger.debug("LiteLLM stream complete: model=%s", request.model)
