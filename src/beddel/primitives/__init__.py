"""Beddel primitives — atomic workflow building blocks.

Provides :func:`register_builtins` to populate a
:class:`~beddel.domain.registry.PrimitiveRegistry` with all built-in
primitives shipped with the SDK.
"""

from __future__ import annotations

from beddel.domain.registry import PrimitiveRegistry

__all__ = [
    "register_builtins",
]


def register_builtins(registry: PrimitiveRegistry) -> None:
    """Register all built-in primitives in the given registry.

    Uses lazy imports to avoid circular dependencies and to keep the
    import footprint minimal when only a subset of primitives is needed.

    Args:
        registry: The :class:`PrimitiveRegistry` to populate.
    """
    from beddel.primitives.call_agent import CallAgentPrimitive
    from beddel.primitives.chat import ChatPrimitive
    from beddel.primitives.guardrail import GuardrailPrimitive
    from beddel.primitives.llm import LLMPrimitive
    from beddel.primitives.output_generator import OutputGeneratorPrimitive
    from beddel.primitives.tool import ToolPrimitive

    registry.register("llm", LLMPrimitive())
    registry.register("chat", ChatPrimitive())
    registry.register("output-generator", OutputGeneratorPrimitive())
    registry.register("guardrail", GuardrailPrimitive())
    registry.register("call-agent", CallAgentPrimitive())
    registry.register("tool", ToolPrimitive())
