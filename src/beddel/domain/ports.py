"""Port interfaces (abstract base classes) for the Beddel hexagonal architecture.

Defines the contracts that adapters and primitives must implement.  These
interfaces live in the domain core and MUST NOT depend on any external
library — only stdlib, ``abc``, typing, and domain models are allowed.

Ports defined here:

- :class:`IExecutionStrategy` — contract for workflow execution strategies.
- :class:`IPrimitive` — contract for all workflow primitives.
- :class:`ILLMProvider` — contract for LLM provider adapters.
- :class:`ILifecycleHook` — contract for workflow lifecycle hooks.
- :class:`IContextReducer` — contract for pluggable context reduction strategies.
- :class:`ITracer` — contract for observability tracing.
- :class:`NoOpTracer` — no-op tracer for testing and explicit opt-out.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

from beddel.domain.models import ExecutionContext, Step, Workflow

SpanT = TypeVar("SpanT")
"""Type variable for the opaque span handle used by :class:`ITracer` implementations."""

if TYPE_CHECKING:
    from beddel.domain.registry import PrimitiveRegistry

__all__ = [
    "SpanT",
    "ExecutionDependencies",
    "IContextReducer",
    "IExecutionStrategy",
    "ILifecycleHook",
    "ILLMProvider",
    "IPrimitive",
    "ITracer",
    "NoOpTracer",
    "StepRunner",
]


StepRunner = Callable[[Step, ExecutionContext], Awaitable[Any]]
"""Type alias for the step-runner callback passed to execution strategies."""


class ExecutionDependencies(Protocol):
    """Typed access to execution context dependencies.

    Defines the structural contract for dependency containers passed to
    the executor via ``ExecutionContext.deps``.  Uses structural subtyping
    (``Protocol``) so any object exposing the required read-only properties
    satisfies the contract without explicit inheritance.

    [Source: Architecture §4.8 — ExecutionDependencies protocol]
    """

    @property
    def llm_provider(self) -> ILLMProvider | None:
        """The LLM provider adapter, or ``None`` if not configured."""
        ...

    @property
    def lifecycle_hooks(self) -> list[ILifecycleHook]:
        """Lifecycle hooks to notify during workflow execution."""
        ...

    @property
    def execution_strategy(self) -> IExecutionStrategy | None:
        """The injected execution strategy, or ``None`` to use the default."""
        ...

    @property
    def delegate_model(self) -> str:
        """Model name used for DELEGATE step LLM calls."""
        ...

    @property
    def workflow_loader(self) -> Callable[[str], Workflow] | None:
        """Callable that loads a sub-workflow by name, or ``None``."""
        ...

    @property
    def registry(self) -> PrimitiveRegistry | None:
        """The primitive registry, or ``None`` if not provided."""
        ...

    @property
    def tool_registry(self) -> dict[str, Callable[..., Any]] | None:
        """Registry of tool callables, or ``None`` if not provided."""
        ...

    @property
    def tracer(self) -> ITracer[Any] | None:
        """The observability tracer, or ``None`` if not configured."""
        ...


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
        step_runner: StepRunner,
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
            step_runner: :data:`StepRunner` callback that executes a single
                step with full lifecycle handling.
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
    provider instance from ``context.deps.llm_provider``.

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


class IContextReducer(Protocol):
    """Contract for pluggable context reduction strategies.

    Planned port for context-window management in chat-based primitives.
    Implementations will provide strategies such as summarization, semantic
    selection, or sliding-window approaches to replace the current FIFO
    truncation in ``ChatPrimitive._apply_context_window()``.

    Planned — not yet wired into any primitive.

    [Source: docs/architecture/6-port-interfaces.md — context reduction]
    """

    async def reduce(
        self,
        messages: list[dict[str, Any]],
        token_budget: int,
    ) -> list[dict[str, Any]]:
        """Reduce a message list to fit within a token budget.

        Receives the full message history and returns a subset (or
        transformed version) that fits within the given token budget.
        The strategy decides which messages to keep, summarize, or
        discard.

        Args:
            messages: The full chat message list, each dict containing
                at least ``"role"`` and ``"content"`` keys.
            token_budget: Maximum number of tokens the returned message
                list should consume.

        Returns:
            A reduced message list that fits within ``token_budget``.
        """
        ...


class ITracer(ABC, Generic[SpanT]):
    """Port interface for observability tracing.

    Defines the contract for trace span management.  Implementations
    bridge the domain core to a tracing backend (e.g. OpenTelemetry).

    The generic type parameter ``SpanT`` represents the opaque span handle
    type used by the concrete implementation (e.g. ``None`` for
    :class:`NoOpTracer`, ``Span`` for an OpenTelemetry adapter).

    Both methods are **synchronous** — OpenTelemetry's span API does not
    perform I/O, so ``async`` is unnecessary.

    [Source: docs/architecture/6-port-interfaces.md#64-itracer]
    """

    @abstractmethod
    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> SpanT | None:
        """Start a trace span.

        Args:
            name: Human-readable span name (e.g. ``"workflow.execute"``).
            attributes: Optional key-value attributes to attach to the span.

        Returns:
            An opaque span handle passed back to :meth:`end_span`, or
            ``None`` if span creation fails.
        """
        ...

    @abstractmethod
    def end_span(self, span: SpanT | None, attributes: dict[str, Any] | None = None) -> None:
        """End a trace span with optional final attributes.

        Args:
            span: The opaque span handle returned by :meth:`start_span`,
                or ``None`` if no span was created.
            attributes: Optional key-value attributes to attach before closing.
        """
        ...


class NoOpTracer(ITracer[None]):
    """No-op tracer for testing and explicit opt-out.

    Returns ``None`` from :meth:`start_span` and silently ignores
    :meth:`end_span`.  Used as the default when no tracing backend
    is configured.
    """

    def start_span(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Return ``None`` — no span is created.

        Args:
            name: Span name (ignored).
            attributes: Span attributes (ignored).

        Returns:
            Always ``None``.
        """
        return None

    def end_span(self, span: None, attributes: dict[str, Any] | None = None) -> None:
        """No-op — silently ignores the call.

        Args:
            span: Span handle (ignored).
            attributes: Final attributes (ignored).
        """
