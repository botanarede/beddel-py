"""Port interfaces (abstract base classes) for the Beddel hexagonal architecture.

Defines the contracts that adapters and primitives must implement.  These
interfaces live in the domain core and MUST NOT depend on any external
library — only stdlib, ``abc``, typing, and domain models are allowed.

Ports defined here:

- :class:`IExecutionStrategy` — contract for workflow execution strategies.
- :class:`IPrimitive` — contract for all workflow primitives.
- :class:`ILLMProvider` — contract for LLM provider adapters.
- :class:`ILifecycleHook` — contract for workflow lifecycle hooks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any, Protocol

from beddel.domain.models import ExecutionContext, Workflow

__all__ = [
    "IExecutionStrategy",
    "ILifecycleHook",
    "ILLMProvider",
    "IPrimitive",
]


class IExecutionStrategy(Protocol):
    """Contract for workflow execution strategies.

    Strategies control how a workflow's steps are iterated and executed.
    The default ``SequentialStrategy`` runs steps in declaration order;
    future strategies (parallel, goal-oriented, reflection) can be
    plugged in without modifying the executor core.

    The ``step_runner`` callback handles all per-step concerns (condition
    evaluation, timeout, error strategies, lifecycle hooks) — the strategy
    only decides *which* steps to run and in *what order*.

    [Source: docs/architecture/6-port-interfaces.md#65-iexecutionstrategy]
    """

    async def execute(
        self,
        workflow: Workflow,
        context: ExecutionContext,
        step_runner: Any,
    ) -> None:
        """Execute the workflow steps using this strategy.

        The strategy iterates the workflow's steps and calls
        ``await step_runner(step, context)`` for each one.  Results are
        stored in ``context.step_results`` as a side-effect of the
        callback — the strategy itself returns ``None``.

        Args:
            workflow: The workflow definition containing steps to execute.
            context: Mutable runtime context carrying inputs, step results,
                and metadata for the current workflow execution.
            step_runner: Async callback ``(step, context) -> Any`` that
                executes a single step with full lifecycle handling.
        """
        ...


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


class ILifecycleHook:
    """Contract for workflow lifecycle hooks.

    Hooks receive notifications at key points during workflow execution.
    All methods have default no-op implementations — subclasses override
    only the callbacks they need.

    Example::

        class LoggingHook(ILifecycleHook):
            async def on_step_start(self, step_id: str, primitive: str) -> None:
                print(f"Starting step {step_id} ({primitive})")
    """

    async def on_workflow_start(self, workflow_id: str, inputs: dict[str, Any]) -> None:
        """Called when a workflow execution begins.

        Args:
            workflow_id: Identifier of the workflow being executed.
            inputs: User-supplied inputs for the workflow run.
        """

    async def on_workflow_end(self, workflow_id: str, result: dict[str, Any]) -> None:
        """Called when a workflow execution completes successfully.

        Args:
            workflow_id: Identifier of the workflow that completed.
            result: The final workflow result dict.
        """

    async def on_step_start(self, step_id: str, primitive: str) -> None:
        """Called before a step begins execution.

        Args:
            step_id: Identifier of the step about to execute.
            primitive: Name of the primitive being invoked.
        """

    async def on_step_end(self, step_id: str, result: Any) -> None:
        """Called after a step completes successfully.

        Args:
            step_id: Identifier of the step that completed.
            result: The step's return value.
        """

    async def on_error(self, step_id: str, error: Exception) -> None:
        """Called when a step encounters an error.

        Args:
            step_id: Identifier of the step that failed.
            error: The exception that was raised.
        """

    async def on_retry(self, step_id: str, attempt: int, error: Exception) -> None:
        """Called when a step retry is attempted.

        Args:
            step_id: Identifier of the step being retried.
            attempt: The retry attempt number (1-based).
            error: The exception that triggered the retry.
        """
