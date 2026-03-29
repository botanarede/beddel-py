"""Port interfaces (abstract base classes) for the Beddel hexagonal architecture.

Defines the contracts that adapters and primitives must implement.  These
interfaces live in the domain core and MUST NOT depend on any external
library — only stdlib, ``abc``, typing, and domain models are allowed.

Ports defined here:

- :class:`IAgentAdapter` — contract for external agent backend adapters.
- :class:`IExecutionStrategy` — contract for workflow execution strategies.
- :class:`IPrimitive` — contract for all workflow primitives.
- :class:`ILLMProvider` — contract for LLM provider adapters.
- :class:`ILifecycleHook` — contract for workflow lifecycle hooks.
- :class:`IHookManager` — contract for hook management (extends ILifecycleHook).
- :class:`IContextReducer` — contract for pluggable context reduction strategies.
- :class:`ITierRouter` — contract for model tier routing strategies.
- :class:`IBudgetEnforcer` — contract for per-workflow budget enforcement.
- :class:`ITracer` — contract for observability tracing.
- :class:`NoOpTracer` — no-op tracer for testing and explicit opt-out.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, runtime_checkable

from beddel.domain.models import AgentResult, ExecutionContext, Step, Workflow

SpanT = TypeVar("SpanT")
"""Type variable for the opaque span handle used by :class:`ITracer` implementations."""

if TYPE_CHECKING:
    from beddel.domain.models import BudgetStatus
    from beddel.domain.registry import PrimitiveRegistry

__all__ = [
    "SpanT",
    "ExecutionDependencies",
    "IAgentAdapter",
    "IBudgetEnforcer",
    "ICircuitBreaker",
    "IContextReducer",
    "IEventStore",
    "IExecutionStrategy",
    "IHookManager",
    "ILifecycleHook",
    "ILLMProvider",
    "IMCPClient",
    "IPrimitive",
    "ITierRouter",
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
    def lifecycle_hooks(self) -> IHookManager | None:
        """Hook manager for lifecycle notifications, or ``None``."""
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

    @property
    def agent_adapter(self) -> IAgentAdapter | None:
        """The default agent adapter, or ``None`` if not configured."""
        ...

    @property
    def agent_registry(self) -> dict[str, IAgentAdapter] | None:
        """Registry of named agent adapters, or ``None`` if not provided."""
        ...

    @property
    def context_reducer(self) -> IContextReducer | None:
        """The context reducer for chat primitives, or ``None`` for FIFO fallback."""
        ...

    @property
    def circuit_breaker(self) -> ICircuitBreaker | None:
        """The circuit breaker for provider fault tolerance, or ``None`` if not configured."""
        ...

    @property
    def event_store(self) -> IEventStore | None:
        """The event store for durable execution, or ``None`` if not configured."""
        ...

    @property
    def mcp_registry(self) -> dict[str, IMCPClient] | None:
        """Registry of named MCP clients, or ``None`` if not configured."""
        ...

    @property
    def tier_router(self) -> ITierRouter | None:
        """The tier router for model tier resolution, or ``None`` if not configured."""
        ...

    @property
    def budget_enforcer(self) -> IBudgetEnforcer | None:
        """The budget enforcer for cost controls, or ``None`` if not configured."""
        ...


class IBudgetEnforcer(Protocol):
    """Contract for per-workflow budget enforcement implementations.

    Tracks cumulative token/cost usage across workflow steps and reports
    the current budget state.  The executor checks the budget after each
    step and triggers degradation or hard-stop behaviour accordingly.

    Uses structural subtyping (``Protocol``) consistent with
    :class:`ITierRouter`, :class:`ICircuitBreaker`, and other Epic 5 ports.

    [Source: docs/stories/epic-5/story-5.6.md — AC 1]
    """

    def track_usage(self, step_id: str, usage: dict[str, Any]) -> None:
        """Record token/cost usage for a completed step.

        Args:
            step_id: Identifier of the step that produced the usage data.
            usage: Usage dict from the LLM provider response, typically
                containing ``prompt_tokens``, ``completion_tokens``, and
                ``total_cost`` keys.
        """
        ...

    def check_budget(self) -> BudgetStatus:
        """Return the current budget state.

        Returns:
            :class:`~beddel.domain.models.BudgetStatus` indicating whether
            the workflow is within budget, degraded, or exceeded.
        """
        ...

    def get_remaining(self) -> float:
        """Return the remaining budget in USD.

        Returns:
            Non-negative float representing the remaining budget.
            Returns ``0.0`` when the budget is fully consumed.
        """
        ...

    @property
    def cumulative_cost(self) -> float:
        """Total cost accumulated so far."""
        ...

    @property
    def max_cost_usd(self) -> float:
        """Hard budget limit in USD."""
        ...

    @property
    def degradation_model(self) -> str:
        """Model identifier used when budget is degraded."""
        ...

    @property
    def degradation_threshold(self) -> float:
        """Fraction of ``max_cost_usd`` that triggers degradation."""
        ...


class ITierRouter(Protocol):
    """Contract for model tier routing strategies.

    Maps logical tier names (e.g. ``"fast"``, ``"balanced"``, ``"powerful"``)
    to concrete model identifiers.  The default implementation performs a
    static dict lookup; future implementations can use bandit-based adaptive
    routing that learns optimal tier-to-model assignments based on prompt
    complexity and observed quality.

    Uses structural subtyping (``Protocol``) consistent with
    :class:`IExecutionStrategy`, :class:`IContextReducer`, and
    :class:`ICircuitBreaker`.

    [Source: docs/stories/epic-5/story-5.5.md — AC 5]
    """

    def route(self, tier: str, prompt_complexity: float | None = None) -> str:
        """Resolve a tier name to a concrete model identifier.

        Args:
            tier: Logical tier name (e.g. ``"fast"``, ``"balanced"``,
                ``"powerful"``).
            prompt_complexity: Optional complexity score for adaptive routing.
                Ignored by static implementations; reserved for future
                bandit-based routers.

        Returns:
            A concrete model identifier string (e.g. ``"gpt-4o-mini"``).

        Raises:
            PrimitiveError: When the tier name is not recognised
                (error code ``BEDDEL-PRIM-320``).
        """
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

    async def on_decision(self, decision: str, alternatives: list[str], rationale: str) -> None:
        """Called when the executor records a decision.

        Prepares the hook surface for Gap #19 (decision capture in Epic 5).
        Implementations can log, audit, or replay decisions made during
        workflow execution.

        Args:
            decision: The decision that was made.
            alternatives: Alternative options that were considered.
            rationale: Explanation for why this decision was chosen.
        """

    async def on_budget_threshold(
        self, workflow_id: str, cumulative_cost: float, threshold: float
    ) -> None:
        """Called when cumulative cost reaches the degradation threshold.

        Fires once per workflow execution when the budget enforcer detects
        that cumulative cost has reached ``degradation_threshold × max_cost_usd``,
        triggering automatic model degradation for remaining steps.

        Args:
            workflow_id: Identifier of the workflow being executed.
            cumulative_cost: The cumulative cost in USD at the time of threshold breach.
            threshold: The degradation threshold value (fraction of ``max_cost_usd``).
        """


class IHookManager(ILifecycleHook):
    """Contract for hook management, extending lifecycle hook notifications.

    Adds hook registration and removal on top of the lifecycle callbacks
    defined by :class:`ILifecycleHook`.  Implementations manage a
    collection of hooks and fan-out lifecycle notifications to all
    registered hooks.

    All methods have default no-op implementations (empty body returns
    ``None``) — subclasses override only the behaviour they need.
    ``IHookManager()`` is therefore a valid null-object instance used as
    the executor fallback when no hook manager is injected.

    Registration methods (``add_hook``/``remove_hook``) are ``async`` for
    uniformity with the lifecycle callbacks and to allow future
    concurrency-safe implementations (e.g. lock-protected registries).
    Implementations MUST keep registration non-blocking.

    Example::

        class CompositeHookManager(IHookManager):
            def __init__(self) -> None:
                self._hooks: list[ILifecycleHook] = []

            async def add_hook(self, hook: ILifecycleHook) -> None:
                self._hooks.append(hook)

            async def remove_hook(self, hook: ILifecycleHook) -> None:
                self._hooks.remove(hook)
    """

    async def add_hook(self, hook: ILifecycleHook) -> None:
        """Register a lifecycle hook.

        Args:
            hook: The lifecycle hook to add.
        """

    async def remove_hook(self, hook: ILifecycleHook) -> None:
        """Remove a previously registered lifecycle hook.

        Args:
            hook: The lifecycle hook to remove.
        """


@runtime_checkable
class IAgentAdapter(Protocol):
    """Generic port for external agent backend adapters.

    Defines the structural contract for integrating external agent backends
    such as Codex, Claude Agent SDK, OpenClaw, and A2A into the Beddel
    workflow engine.  Uses structural subtyping (``Protocol``) so any object
    exposing the required methods satisfies the contract without explicit
    inheritance.

    This port fills the gap between :class:`ILLMProvider` (stateless text
    completion) and :class:`IExecutionStrategy` (full workflow delegation),
    providing a mid-level abstraction for agent-style interactions that may
    involve tool use, sandboxed execution, and structured output.

    [Source: docs/architecture/23-unified-agent-adapter.md §23.2]
    """

    async def execute(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute a prompt against the agent backend.

        Sends a prompt to the external agent and waits for a complete
        result.  The agent may use tools, modify files in a sandbox,
        and return structured output.

        Args:
            prompt: The instruction or task to send to the agent.
            model: Optional model override for the agent backend.
                Defaults to the adapter's configured model when ``None``.
            sandbox: Sandbox access level for the agent execution.
                One of ``"read-only"``, ``"workspace-write"``, or
                ``"danger-full-access"``.
            tools: Optional list of tool names the agent is allowed to use.
                Defaults to the adapter's configured tool set when ``None``.
            output_schema: Optional JSON Schema dict for structured output.
                When provided, the agent should return output conforming
                to this schema.

        Returns:
            An :class:`~beddel.domain.models.AgentResult` containing the
            agent's exit code, output text, events, changed files, usage
            metrics, and agent identifier.
        """
        ...

    async def stream(
        self,
        prompt: str,
        *,
        model: str | None = None,
        sandbox: str = "read-only",
        tools: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events from the agent backend.

        Sends a prompt to the external agent and yields structured event
        dicts as they arrive.  Useful for real-time progress monitoring
        and incremental output display.

        Args:
            prompt: The instruction or task to send to the agent.
            model: Optional model override for the agent backend.
                Defaults to the adapter's configured model when ``None``.
            sandbox: Sandbox access level for the agent execution.
                One of ``"read-only"``, ``"workspace-write"``, or
                ``"danger-full-access"``.
            tools: Optional list of tool names the agent is allowed to use.
                Defaults to the adapter's configured tool set when ``None``.

        Yields:
            Structured event dicts from the agent execution stream.
        """
        ...  # pragma: no cover
        # yield is required for the type checker to recognise this as an
        # async generator; the ellipsis body is the Protocol convention.
        yield {}  # type: ignore[misc]  # pragma: no cover


class IContextReducer(Protocol):
    """Contract for pluggable context reduction strategies.

    Port for context-window management in chat-based primitives.
    Implementations provide strategies such as summarization, semantic
    selection, or sliding-window approaches to replace the current FIFO
    truncation in ``ChatPrimitive._apply_context_window()``.

    Wired into ``ChatPrimitive`` as of Story 4.0d.  When a reducer is
    injected via ``context.deps.context_reducer`` and ``max_context_tokens``
    is set, the primitive delegates to ``reduce()`` instead of FIFO.

    Invariants:
        Implementations MUST return valid message sequences.  In particular:

        - Tool-call assistant messages (containing ``tool_calls``) and their
          corresponding tool-response messages (``role: "tool"``) MUST be
          kept as atomic pairs.  Dropping one side produces invalid sequences
          that LLM providers reject with a 400 error.
        - The returned list MUST fit within ``token_budget``.
        - Message ordering MUST be preserved (no reordering).

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


class ICircuitBreaker(Protocol):
    """Contract for per-provider circuit breaker implementations.

    Tracks failure/success rates per provider and controls whether
    requests should be short-circuited to a fallback.  The circuit
    transitions through three states: CLOSED → OPEN → HALF_OPEN → CLOSED.

    Implementations MUST be thread-safe — the circuit breaker may be
    shared across concurrent async tasks.

    [Source: docs/architecture/6-port-interfaces.md §6.10]
    """

    def record_failure(self, provider: str) -> None:
        """Record a failed request for the given provider.

        Increments the failure counter.  When the failure threshold is
        reached, the circuit transitions to OPEN.

        Args:
            provider: Identifier of the provider that failed.
        """
        ...

    def record_success(self, provider: str) -> None:
        """Record a successful request for the given provider.

        Resets the failure counter.  In HALF_OPEN state, increments the
        success counter and transitions to CLOSED when the success
        threshold is reached.

        Args:
            provider: Identifier of the provider that succeeded.
        """
        ...

    def is_open(self, provider: str) -> bool:
        """Check whether the circuit is open for the given provider.

        Returns ``True`` when requests should be short-circuited (OPEN
        state within the recovery window).  Returns ``False`` for CLOSED,
        HALF_OPEN, or OPEN-past-recovery-window (which transitions to
        HALF_OPEN).

        Args:
            provider: Identifier of the provider to check.

        Returns:
            ``True`` if the circuit is open and requests should be blocked.
        """
        ...

    def state(self, provider: str) -> str:
        """Return the current circuit state for the given provider.

        Unknown providers return ``"closed"`` (default state).

        Args:
            provider: Identifier of the provider to query.

        Returns:
            One of ``"closed"``, ``"open"``, or ``"half-open"``.
        """
        ...


class IEventStore(Protocol):
    """Contract for durable event store implementations.

    Provides append-only event logging per workflow, with load and truncate
    operations for checkpoint-based replay.  Implementations MUST be
    thread-safe — the event store may be shared across concurrent async
    tasks.

    [Source: docs/architecture/6-port-interfaces.md §6.8]
    """

    async def append(self, workflow_id: str, step_id: str, event: dict[str, Any]) -> None:
        """Append an event for a workflow step.

        Args:
            workflow_id: Identifier of the workflow execution.
            step_id: Identifier of the step that produced the event.
            event: Arbitrary event payload to store.
        """
        ...

    async def load(self, workflow_id: str) -> list[dict[str, Any]]:
        """Load all events for a workflow in insertion order.

        Args:
            workflow_id: Identifier of the workflow execution.

        Returns:
            List of stored event dicts, in insertion order.
        """
        ...

    async def truncate(self, workflow_id: str) -> None:
        """Remove all events for a workflow.

        Args:
            workflow_id: Identifier of the workflow execution to clear.
        """
        ...


class IMCPClient(Protocol):
    """Port interface for Model Context Protocol (MCP) server clients.

    Implementations bridge the tool primitive to external MCP servers,
    enabling access to the MCP tool ecosystem without custom adapters.
    Transport-agnostic — concrete clients handle stdio, SSE, or HTTP
    communication.

    Uses structural subtyping (``Protocol``) consistent with
    :class:`IEventStore`, :class:`ICircuitBreaker`, and other Epic 4 ports.

    [Source: docs/architecture/6-port-interfaces.md §6.9]
    """

    async def connect(self, server_uri: str) -> None:
        """Establish connection to an MCP server.

        Args:
            server_uri: Server URI (e.g., ``"stdio://mcp-server"`` or
                ``"sse://localhost:8080/mcp"``).
        """
        ...

    async def list_tools(self) -> list[dict[str, Any]]:
        """Discover available tools on the connected server.

        Returns:
            List of tool descriptors with name, description, and
            input schema for each available tool.
        """
        ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool on the connected server.

        Args:
            name: Tool name as returned by :meth:`list_tools`.
            arguments: Tool arguments matching the tool's input schema.

        Returns:
            Tool execution result.
        """
        ...

    async def disconnect(self) -> None:
        """Close the connection to the MCP server."""
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
