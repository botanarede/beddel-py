"""LiteLLM adapter — multi-provider LLM access via the ``ILLMProvider`` port.

This adapter bridges the Beddel domain core to `LiteLLM`_, enabling
transparent access to 100+ LLM providers through a single interface.

API keys are resolved explicitly from well-known environment variables
based on the model prefix, falling back to a constructor-supplied default
and finally to LiteLLM's own auto-detection.

.. _LiteLLM: https://docs.litellm.ai/
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

import litellm
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    Timeout,
)

from beddel.domain.errors import AdapterError
from beddel.domain.ports import ILLMProvider
from beddel.error_codes import ADAPT_AUTH_FAILURE, ADAPT_PROVIDER_ERROR, ADAPT_TIMEOUT

__all__ = ["LiteLLMAdapter"]

# ---------------------------------------------------------------------------
# Model-prefix → environment variable mapping
# ---------------------------------------------------------------------------

_PREFIX_ENV_MAP: dict[str, str] = {
    "openai/": "OPENAI_API_KEY",
    "anthropic/": "ANTHROPIC_API_KEY",
    "gemini/": "GEMINI_API_KEY",
    "bedrock/": "AWS_ACCESS_KEY_ID",
    "azure/": "AZURE_API_KEY",
    "cohere/": "COHERE_API_KEY",
    "mistral/": "MISTRAL_API_KEY",
}


class LiteLLMAdapter(ILLMProvider):
    """Multi-provider LLM adapter powered by LiteLLM.

    Implements :class:`~beddel.domain.ports.ILLMProvider` to provide both
    single-turn completion and streaming access to any LiteLLM-supported
    model.

    API key resolution order (per request):

    1. Explicit ``api_key`` kwarg passed to :meth:`complete`/:meth:`stream`.
    2. Well-known environment variable matched by model prefix
       (e.g. ``OPENAI_API_KEY`` for ``openai/gpt-4o``).
    3. ``default_api_key`` supplied at construction time.
    4. ``None`` — LiteLLM attempts its own auto-detection as a last resort.

    Args:
        default_api_key: Optional fallback API key used when neither an
            explicit kwarg nor a prefix-matched env var is available.

    Example::

        adapter = LiteLLMAdapter()
        result = await adapter.complete(
            model="gemini/gemini-2.0-flash",
            messages=[{"role": "user", "content": "Hello!"}],
        )
        print(result["content"])
    """

    def __init__(self, default_api_key: str | None = None) -> None:
        self._default_api_key = default_api_key

    # ------------------------------------------------------------------
    # API key resolution
    # ------------------------------------------------------------------

    def _resolve_api_key(self, model: str, explicit_key: str | None = None) -> str | None:
        """Resolve the API key for a given model string.

        Args:
            model: LiteLLM model identifier (e.g. ``"gemini/gemini-2.0-flash"``).
            explicit_key: An API key explicitly passed by the caller, which
                takes highest priority.

        Returns:
            The resolved API key, or ``None`` if no key could be determined
            (LiteLLM will attempt its own resolution in that case).
        """
        if explicit_key is not None:
            return explicit_key

        for prefix, env_var in _PREFIX_ENV_MAP.items():
            if model.startswith(prefix):
                value = os.environ.get(env_var)
                if value:
                    return value
                break

        # Models without a recognised prefix default to OpenAI
        if "/" not in model:
            value = os.environ.get("OPENAI_API_KEY")
            if value:
                return value

        return self._default_api_key

    # ------------------------------------------------------------------
    # ILLMProvider implementation
    # ------------------------------------------------------------------

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a completion request and return the full response.

        Args:
            model: LiteLLM model identifier (e.g. ``"openai/gpt-4o"``).
            messages: Chat-style message list with ``"role"`` and
                ``"content"`` keys.
            **kwargs: Forwarded to ``litellm.acompletion`` (e.g.
                ``temperature``, ``max_tokens``, ``api_key``).

        Returns:
            A dict with keys ``"content"``, ``"model"``, ``"usage"``, and
            ``"finish_reason"``.

        Raises:
            AdapterError: On authentication, provider, or connectivity
                failures (codes ``BEDDEL-ADAPT-001`` through ``003``).
        """
        api_key = self._resolve_api_key(model, kwargs.pop("api_key", None))
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                api_key=api_key,
                **kwargs,
            )
        except AuthenticationError as exc:
            raise AdapterError(
                code=ADAPT_AUTH_FAILURE,
                message=f"Provider authentication failure for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc
        except (Timeout, APIConnectionError) as exc:
            raise AdapterError(
                code=ADAPT_TIMEOUT,
                message=f"Timeout or connection error for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc
        except (APIError, RateLimitError, BadRequestError) as exc:
            raise AdapterError(
                code=ADAPT_PROVIDER_ERROR,
                message=f"Provider error for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc

        choice = response.choices[0]  # type: ignore[union-attr]
        usage = response.usage  # type: ignore[union-attr]
        result: dict[str, Any] = {
            "content": choice.message.content,
            "model": response.model,  # type: ignore[union-attr]
            "usage": {
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            },
            "finish_reason": choice.finish_reason,
        }
        if choice.message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]
        return result

    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream completion tokens from the LLM.

        Args:
            model: LiteLLM model identifier (e.g. ``"anthropic/claude-3-opus"``).
            messages: Chat-style message list with ``"role"`` and
                ``"content"`` keys.
            **kwargs: Forwarded to ``litellm.acompletion`` (e.g.
                ``temperature``, ``max_tokens``, ``api_key``).

        Yields:
            String chunks of the model's response as they arrive.

        Raises:
            AdapterError: On authentication, provider, or connectivity
                failures (codes ``BEDDEL-ADAPT-001`` through ``003``).
        """
        api_key = self._resolve_api_key(model, kwargs.pop("api_key", None))
        try:
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                api_key=api_key,
                stream=True,
                **kwargs,
            )
        except AuthenticationError as exc:
            raise AdapterError(
                code=ADAPT_AUTH_FAILURE,
                message=f"Provider authentication failure for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc
        except (Timeout, APIConnectionError) as exc:
            raise AdapterError(
                code=ADAPT_TIMEOUT,
                message=f"Timeout or connection error for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc
        except (APIError, RateLimitError, BadRequestError) as exc:
            raise AdapterError(
                code=ADAPT_PROVIDER_ERROR,
                message=f"Provider error for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc

        try:
            async for chunk in response:  # type: ignore[union-attr]
                delta = chunk.choices[0].delta  # type: ignore[union-attr]
                if delta.content is not None:
                    yield delta.content
        except AuthenticationError as exc:
            raise AdapterError(
                code=ADAPT_AUTH_FAILURE,
                message=f"Provider authentication failure for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc
        except (Timeout, APIConnectionError) as exc:
            raise AdapterError(
                code=ADAPT_TIMEOUT,
                message=f"Timeout or connection error for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc
        except (APIError, RateLimitError, BadRequestError) as exc:
            raise AdapterError(
                code=ADAPT_PROVIDER_ERROR,
                message=f"Provider error for model '{model}': {exc}",
                details={"model": model, "provider_error": str(exc)},
            ) from exc
