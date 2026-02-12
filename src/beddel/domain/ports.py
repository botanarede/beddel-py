"""Port interfaces (abstract base classes) for the Beddel hexagonal architecture.

Defines the contracts that adapters and primitives must implement.  These
interfaces live in the domain core and MUST NOT depend on any external
library — only stdlib, ``abc``, typing, and domain models are allowed.

Ports defined here:

- :class:`IPrimitive` — contract for all workflow primitives.
- :class:`ILLMProvider` — contract for LLM provider adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.models import ExecutionContext

__all__ = [
    "ILLMProvider",
    "IPrimitive",
]


class IPrimitive(ABC):
    """Contract for all workflow primitives.

    Every primitive registered in the Beddel registry must implement this
    interface.  The executor calls :meth:`execute` with the step's config
    dict and the current :class:`ExecutionContext`.

    Example::

        class MyPrimitive(IPrimitive):
            async def execute(
                self, config: dict[str, Any], context: ExecutionContext
            ) -> Any:
                return {"result": config["value"]}
    """

    @abstractmethod
    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Execute the primitive with the given configuration and context.

        Args:
            config: Primitive-specific configuration dict from the workflow
                step definition.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.

        Returns:
            The primitive's result value, which will be stored in
            ``context.step_results[step_id]``.

        Raises:
            PrimitiveError: When the primitive encounters an execution failure.
        """


class ILLMProvider(ABC):
    """Contract for LLM provider adapters.

    Implementations bridge the domain core to a specific LLM backend
    (e.g. LiteLLM, OpenAI, Anthropic).  The ``llm`` primitive reads the
    provider instance from ``context.metadata["llm_provider"]`` (AC-7).

    Example::

        class MyLLMProvider(ILLMProvider):
            async def complete(
                self, model: str, messages: list[dict[str, Any]], **kwargs: Any
            ) -> dict[str, Any]:
                return {"content": "Hello!", "usage": {}}

            async def stream(
                self, model: str, messages: list[dict[str, Any]], **kwargs: Any
            ) -> AsyncGenerator[str, None]:
                yield "Hello"
                yield "!"
    """

    @abstractmethod
    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a single-turn completion request to the LLM.

        Args:
            model: Model identifier (e.g. ``"gpt-4o"``, ``"claude-3-opus"``).
            messages: Chat-style message list, each dict containing at least
                ``"role"`` and ``"content"`` keys.
            **kwargs: Additional provider-specific parameters such as
                ``temperature``, ``max_tokens``, ``top_p``, etc.

        Returns:
            A dict containing at minimum a ``"content"`` key with the model's
            response text.  Implementations may include additional keys such
            as ``"usage"``, ``"model"``, or ``"finish_reason"``.

        Raises:
            AdapterError: When the LLM provider call fails.
        """

    @abstractmethod
    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Stream completion tokens from the LLM.

        Args:
            model: Model identifier (e.g. ``"gpt-4o"``, ``"claude-3-opus"``).
            messages: Chat-style message list, each dict containing at least
                ``"role"`` and ``"content"`` keys.
            **kwargs: Additional provider-specific parameters such as
                ``temperature``, ``max_tokens``, ``top_p``, etc.

        Yields:
            String chunks of the model's response as they arrive.

        Raises:
            AdapterError: When the LLM provider call fails.
        """
        # https://docs.python.org/3/library/abc.html — yield required for
        # abstract async generators so the method is recognised as a generator.
        yield ""  # pragma: no cover
