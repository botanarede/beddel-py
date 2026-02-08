"""Built-in primitives — llm, chat, output, call-agent, guardrail, tool."""

from __future__ import annotations

from typing import TYPE_CHECKING

from beddel.primitives.chat import chat_primitive
from beddel.primitives.llm import llm_primitive
from beddel.primitives.output import output_primitive

if TYPE_CHECKING:
    from beddel.domain.registry import PrimitiveRegistry


def register_builtins(registry: PrimitiveRegistry) -> None:
    """Register all built-in primitives with the given registry."""
    registry.register_func("llm", llm_primitive)
    registry.register_func("chat", chat_primitive)
    registry.register_func("output-generator", output_primitive)
