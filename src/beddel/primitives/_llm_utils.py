"""Internal shared utilities for LLM-based primitives.

This module contains validation and configuration helpers shared by
:class:`~beddel.primitives.llm.LLMPrimitive` and
:class:`~beddel.primitives.chat.ChatPrimitive`.

The underscore prefix on the filename signals that this is **not** part of
the public API — consumers should interact with the primitives themselves,
not with these helpers directly.
"""

from __future__ import annotations

from typing import Any

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import ILLMProvider
from beddel.error_codes import PRIM_MISSING_MODEL, PRIM_MISSING_PROVIDER

__all__ = ["get_provider", "get_model", "build_kwargs"]


def get_provider(context: ExecutionContext, primitive_type: str) -> ILLMProvider:
    """Extract and validate the LLM provider from context deps.

    Args:
        context: The current execution context.
        primitive_type: Identifier for the calling primitive (e.g. ``"llm"``,
            ``"chat"``), included in error details.

    Returns:
        The :class:`ILLMProvider` instance.

    Raises:
        PrimitiveError: ``BEDDEL-PRIM-003`` if ``llm_provider`` is
            missing from deps or does not implement :class:`ILLMProvider`.
    """
    provider = context.deps.llm_provider
    if provider is None:
        raise PrimitiveError(
            PRIM_MISSING_PROVIDER,
            "Missing 'llm_provider' in execution context deps",
            {
                "step_id": context.current_step_id,
                "primitive_type": primitive_type,
            },
        )
    if not isinstance(provider, ILLMProvider):
        raise PrimitiveError(
            PRIM_MISSING_PROVIDER,
            "llm_provider in context.deps does not implement ILLMProvider",
            {
                "step_id": context.current_step_id,
                "primitive_type": primitive_type,
                "provider_type": type(provider).__name__,
            },
        )
    return provider


def get_model(config: dict[str, Any], context: ExecutionContext, primitive_type: str) -> str:
    """Extract, validate, and resolve the model identifier from config.

    If a :class:`~beddel.domain.ports.ITierRouter` is available in
    ``context.deps``, the model value is first attempted as a tier name
    (e.g. ``"fast"``, ``"balanced"``, ``"powerful"``).  If the router
    recognises it, the resolved concrete model is returned; otherwise the
    value is used as-is, preserving backward compatibility with concrete
    model names like ``"gpt-4o"``.

    Args:
        config: Primitive configuration dict.
        context: The current execution context (for error details and deps).
        primitive_type: Identifier for the calling primitive (e.g. ``"llm"``,
            ``"chat"``), included in error details.

    Returns:
        The concrete model identifier string.

    Raises:
        PrimitiveError: ``BEDDEL-PRIM-004`` if ``model`` is missing.
    """
    model = config.get("model")
    if model is None:
        raise PrimitiveError(
            PRIM_MISSING_MODEL,
            "Missing required config key: 'model'",
            {
                "step_id": context.current_step_id,
                "primitive_type": primitive_type,
                "missing_key": "model",
            },
        )

    # Budget degradation override (highest priority)
    if context.metadata.get("_budget_degraded"):
        return context.metadata["_degradation_model"]

    # Tier resolution: if tier_router is available, try to resolve
    tier_router = context.deps.tier_router
    if tier_router is not None:
        try:
            return tier_router.route(model)
        except PrimitiveError:
            pass  # Not a tier name — fall through to use as concrete model

    return model


def build_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    """Extract optional provider kwargs from config.

    Picks ``temperature``, ``max_tokens``, and ``effort`` if present.

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
    if "effort" in config:
        kwargs["effort"] = config["effort"]
    return kwargs
