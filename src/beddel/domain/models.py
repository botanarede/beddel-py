"""Pydantic 2.x data models for the Beddel workflow schema.

Defines the core domain types used throughout the SDK: workflows, steps,
execution strategies, events, and execution context.  All models use
Pydantic v2 ``BaseModel`` with strict type annotations.

Only stdlib + pydantic imports are allowed in this module (domain core rule).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from beddel.domain.errors import StateError
from beddel.error_codes import STATE_CORRUPTED

if TYPE_CHECKING:
    from beddel.domain.ports import (
        IAgentAdapter,
        IApprovalGate,
        IBudgetEnforcer,
        ICircuitBreaker,
        IContextReducer,
        IEventStore,
        IExecutionStrategy,
        IHookManager,
        ILLMProvider,
        IPIITokenizer,
        IStateStore,
        ITierRouter,
        ITracer,
    )
    from beddel.domain.registry import PrimitiveRegistry

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# PII tokenization types  (Epic 6 — PII Tokenization)
# ---------------------------------------------------------------------------

TokenMap = dict[str, str]
"""Mapping of PII token placeholders to their original values."""


@dataclass(frozen=True)
class PIIPattern:
    """Definition of a PII pattern for regex-based tokenization."""

    name: str
    pattern: str
    replacement_prefix: str


__all__ = [
    "AgentResult",
    "ApprovalPolicy",
    "ApprovalResult",
    "ApprovalStatus",
    "BackoffType",
    "BeddelEvent",
    "BudgetStatus",
    "CircuitBreakerConfig",
    "CircuitState",
    "DefaultDependencies",
    "ErrorSemantics",
    "EventType",
    "ExecutionContext",
    "ExecutionStrategy",
    "GoalConfig",
    "InterruptibleContext",
    "PIIPattern",
    "ParallelConfig",
    "RetryConfig",
    "RiskLevel",
    "RiskMatrix",
    "SKIPPED",
    "Step",
    "StrategyType",
    "TierConfig",
    "TokenMap",
    "ToolDeclaration",
    "Workflow",
]


class _Skipped:
    """Sentinel for skipped step results (condition was falsy).

    Replaces ``None`` in ``context.step_results`` when a step's
    ``if_condition`` evaluates to false.  Falsy like ``None`` but
    distinguishable via identity (``result is SKIPPED``).
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        """Return ``False`` — SKIPPED is falsy."""
        return False

    def __repr__(self) -> str:
        """Return ``'SKIPPED'``."""
        return "SKIPPED"


SKIPPED = _Skipped()
"""Module-level sentinel instance for skipped step results."""


@dataclass
class AgentResult:
    """Result of an agent adapter execution.

    Returned by :class:`~beddel.domain.ports.IAgentAdapter` implementations
    after executing a prompt against an external agent backend (e.g. Codex,
    Claude Agent SDK, OpenClaw, A2A).

    Attributes:
        exit_code: Process exit code from the agent execution (0 = success).
        output: The agent's text output or response.
        events: List of structured events emitted during execution.
        files_changed: Paths of files created or modified by the agent.
        usage: Token usage and cost information from the agent backend.
        agent_id: Identifier of the agent that produced this result.
    """

    exit_code: int
    output: str
    events: list[dict[str, Any]]
    files_changed: list[str]
    usage: dict[str, Any]
    agent_id: str


# ---------------------------------------------------------------------------
# Approval gate domain types  (Epic 6 — HOTL)
# ---------------------------------------------------------------------------


class RiskLevel(StrEnum):
    """Risk classification for agent actions.

    Used by :class:`RiskMatrix` and :class:`ApprovalPolicy` to determine
    whether an action requires human approval.

    - ``LOW``: Read-only, fully reversible — auto-approve.
    - ``MEDIUM``: Write actions, partially reversible — review.
    - ``HIGH``: Destructive, irreversible — require approval.
    - ``CRITICAL``: System-level, catastrophic potential — always block.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(StrEnum):
    """Status of an approval request through its lifecycle.

    - ``PENDING``: Awaiting human decision.
    - ``APPROVED``: Human approved the action.
    - ``DENIED``: Human denied the action.
    - ``TIMEOUT``: No response within the configured window.
    - ``ESCALATED``: Timeout triggered escalation policy.
    """

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class ApprovalResult:
    """Immutable result of an approval gate decision.

    Returned by :class:`~beddel.domain.ports.IApprovalGate` after a human
    (or policy) resolves an approval request.

    Attributes:
        request_id: Unique identifier for the approval request.
        status: Current status of the approval.
        approver: Identity of the approver, or ``None`` for policy decisions.
        timestamp: Unix timestamp when the decision was made.
        metadata: Arbitrary metadata attached to the result.
    """

    request_id: str
    status: ApprovalStatus
    approver: str | None = None
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ApprovalPolicy(BaseModel):
    """Configuration for risk-based approval policies.

    Controls which risk levels are auto-approved, timeout behaviour, and
    escalation strategy when no human responds.

    Attributes:
        auto_approve_levels: Risk levels that bypass human approval.
        timeout_seconds: Seconds to wait for human response before escalation.
        escalation_policy: What to do on timeout — ``"auto-approve"``,
            ``"auto-deny"``, or ``"delegate"``.
        risk_matrix: Custom action-to-risk-level overrides.
    """

    auto_approve_levels: list[RiskLevel] = Field(
        default_factory=lambda: [RiskLevel.LOW],
    )
    timeout_seconds: float = 300.0
    escalation_policy: str = "auto-deny"
    risk_matrix: dict[str, RiskLevel] = Field(default_factory=dict)


class RiskMatrix:
    """Classifies actions into risk levels using prefix matching.

    Default patterns follow the stakes × reversibility matrix:

    - ``read*``, ``get*``, ``list*``, ``describe*`` → LOW
    - ``write*``, ``update*``, ``create*``, ``put*`` → MEDIUM
    - ``delete*``, ``remove*``, ``drop*``, ``destroy*`` → HIGH
    - Fallback → MEDIUM

    Custom overrides can be supplied via the ``overrides`` dict, which
    maps exact action names to risk levels (checked before prefix matching).
    """

    _LOW_PREFIXES: tuple[str, ...] = ("read", "get", "list", "describe")
    _MEDIUM_PREFIXES: tuple[str, ...] = ("write", "update", "create", "put")
    _HIGH_PREFIXES: tuple[str, ...] = ("delete", "remove", "drop", "destroy")

    def __init__(self, overrides: dict[str, RiskLevel] | None = None) -> None:
        self._overrides: dict[str, RiskLevel] = overrides or {}

    def classify(self, action: str) -> RiskLevel:
        """Classify an action string into a :class:`RiskLevel`.

        Checks exact overrides first, then prefix matching, then falls
        back to ``MEDIUM``.
        """
        if action in self._overrides:
            return self._overrides[action]

        lower = action.lower()
        if lower.startswith(self._LOW_PREFIXES):
            return RiskLevel.LOW
        if lower.startswith(self._MEDIUM_PREFIXES):
            return RiskLevel.MEDIUM
        if lower.startswith(self._HIGH_PREFIXES):
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM


class StrategyType(StrEnum):
    """Execution strategy types for step error handling.

    Each value maps to a different failure-recovery behaviour:

    - ``FAIL``: Abort the workflow immediately (default).
    - ``SKIP``: Ignore the error and continue to the next step.
    - ``RETRY``: Re-execute the step according to ``RetryConfig``.
    - ``FALLBACK``: Execute an alternative fallback step.
    - ``DELEGATE``: Agent-judged recovery — LLM decides retry, skip, or fallback (see §14.3).
    """

    FAIL = "fail"
    SKIP = "skip"
    RETRY = "retry"
    FALLBACK = "fallback"
    DELEGATE = "delegate"


class RetryConfig(BaseModel):
    """Configuration for step retry behaviour.

    Controls exponential back-off with optional jitter when a step is
    configured with ``StrategyType.RETRY``.

    Attributes:
        max_attempts: Maximum number of retry attempts (including the first).
        backoff_base: Base multiplier for exponential back-off in seconds.
        backoff_max: Upper bound for the back-off delay in seconds.
        jitter: Whether to add random jitter to the delay.
    """

    max_attempts: int = 3
    backoff_base: float = 2.0
    backoff_max: float = 60.0
    jitter: bool = True


class ErrorSemantics(StrEnum):
    """Error handling semantics for parallel step groups.

    Controls how errors are propagated when multiple steps run concurrently:

    - ``FAIL_FAST``: Abort remaining branches on first failure (default).
    - ``COLLECT_ALL``: Run all branches to completion, then aggregate errors.
    """

    FAIL_FAST = "fail-fast"
    COLLECT_ALL = "collect-all"


class ParallelConfig(BaseModel):
    """Configuration for parallel step execution.

    Controls concurrency limits, error propagation semantics, and context
    isolation for steps running in a parallel group.

    Attributes:
        concurrency_limit: Maximum number of branches executing concurrently.
        error_semantics: How errors are propagated across parallel branches.
        isolate_context: Whether each branch receives an isolated context copy.
    """

    concurrency_limit: int = 5
    error_semantics: ErrorSemantics = ErrorSemantics.FAIL_FAST
    isolate_context: bool = False


class CircuitState(StrEnum):
    """State of a circuit breaker protecting a provider.

    - ``CLOSED``: Normal operation — requests flow through.
    - ``OPEN``: Circuit tripped — requests are short-circuited to fallback.
    - ``HALF_OPEN``: Recovery probe in progress — a single request is allowed through.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class CircuitBreakerConfig(BaseModel):
    """Configuration for the per-provider circuit breaker.

    Controls when the circuit opens after consecutive failures and how
    recovery is attempted.

    Attributes:
        failure_threshold: Number of consecutive failures before the circuit opens.
        recovery_window: Seconds to wait in the open state before attempting a probe.
        success_threshold: Consecutive successes in half-open state to close the circuit.
    """

    failure_threshold: int = 5
    recovery_window: float = 60.0
    success_threshold: int = 2


class TierConfig(BaseModel):
    """Configuration for model tier-to-identifier mapping.

    Maps logical tier names (e.g. ``"fast"``, ``"balanced"``, ``"powerful"``)
    to concrete model identifiers used by LLM providers.

    Attributes:
        tiers: Mapping of tier names to model identifier strings.
    """

    tiers: dict[str, str]


class BudgetStatus(StrEnum):
    """Current budget state returned by :meth:`IBudgetEnforcer.check_budget`.

    - ``WITHIN_BUDGET``: Cumulative cost is below the degradation threshold.
    - ``DEGRADED``: Cumulative cost has reached the degradation threshold;
      subsequent steps should use the degradation model.
    - ``EXCEEDED``: Cumulative cost has exceeded ``max_cost_usd``; the
      workflow should be stopped.
    """

    WITHIN_BUDGET = "within_budget"
    DEGRADED = "degraded"
    EXCEEDED = "exceeded"


class BackoffType(StrEnum):
    """Backoff strategy for goal-oriented execution loops.

    Controls the delay between goal attempts:

    - ``FIXED``: Constant delay equal to ``backoff_base``.
    - ``EXPONENTIAL``: Doubling delay capped at ``backoff_max``.
    - ``ADAPTIVE``: Delay proportional to iteration progress.
    """

    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    ADAPTIVE = "adaptive"


class GoalConfig(BaseModel):
    """Configuration for goal-oriented execution loops.

    Defines the goal condition, attempt limits, and backoff behaviour
    for :class:`GoalOrientedStrategy`.

    Attributes:
        goal_condition: Expression evaluated after each iteration to
            determine whether the goal has been met.
        max_attempts: Maximum number of loop iterations before failure.
        backoff_type: Backoff strategy between attempts.
        backoff_base: Base delay in seconds for backoff calculation.
        backoff_max: Upper bound for the backoff delay in seconds.
    """

    goal_condition: str
    max_attempts: int = 10
    backoff_type: BackoffType = BackoffType.EXPONENTIAL
    backoff_base: float = 1.0
    backoff_max: float = 30.0


class ExecutionStrategy(BaseModel):
    """Strategy applied when a step encounters an error.

    Attributes:
        type: The strategy variant to use (default ``FAIL``).
        retry: Optional retry configuration (used when ``type`` is ``RETRY``).
        fallback_step: Optional fallback step (used when ``type`` is ``FALLBACK``).
    """

    type: StrategyType = StrategyType.FAIL
    retry: RetryConfig | None = None
    fallback_step: Step | None = None


class Step(BaseModel):
    """A single executable step within a workflow.

    Steps reference a primitive by name and carry an arbitrary config dict
    that is forwarded to the primitive at execution time.  Conditional
    branching is supported via ``if``/``then``/``else`` fields.

    Attributes:
        id: Unique identifier for this step within the workflow.
        primitive: Name of the primitive to execute (e.g. ``"llm"``).
        config: Primitive-specific configuration dict.
        if_condition: Optional expression evaluated at runtime for branching.
        then_steps: Steps executed when ``if_condition`` is truthy.
        else_steps: Steps executed when ``if_condition`` is falsy.
        execution_strategy: Error-handling strategy for this step.
        timeout: Optional timeout in seconds for step execution.
        stream: Whether to stream output from this step.
        parallel: Reserved for Epic 4 — parallel execution flag.
        metadata: Arbitrary metadata attached to the step.
        tags: Optional tags for step-level filtering by execution strategies.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    primitive: str
    config: dict[str, Any] = Field(default_factory=dict)
    if_condition: str | None = Field(None, alias="if")
    then_steps: list[Step] | None = Field(None, alias="then")
    else_steps: list[Step] | None = Field(None, alias="else")
    execution_strategy: ExecutionStrategy = Field(
        default_factory=lambda: ExecutionStrategy(type=StrategyType.FAIL)
    )
    timeout: float | None = None
    stream: bool = False
    parallel: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class DefaultDependencies:
    """Concrete dependency container for workflow execution.

    Provides typed access to the LLM provider, lifecycle hooks, execution
    strategy, and delegate model name, satisfying the
    :class:`~beddel.domain.ports.ExecutionDependencies` protocol via
    structural subtyping.

    Args:
        llm_provider: The LLM provider adapter, or ``None`` if not configured.
        lifecycle_hooks: Hook manager for lifecycle notifications,
            or ``None`` if not configured.
        execution_strategy: Optional execution strategy controlling how
            workflow steps are iterated.  Defaults to ``None``, which
            causes the executor to fall back to :class:`SequentialStrategy`.
        delegate_model: Model name used for DELEGATE step LLM calls.
            Defaults to ``"gpt-4o-mini"``.
        workflow_loader: Callable that loads a sub-workflow by name,
            or ``None`` if not configured.
        registry: The primitive registry, or ``None`` if not provided.
        tool_registry: Registry of tool callables keyed by name,
            or ``None`` if not provided.
        tracer: The observability tracer, or ``None`` if not configured.
            Defaults to ``None``.
        agent_adapter: The default agent adapter, or ``None`` if not
            configured.  Defaults to ``None``.
        agent_registry: Registry of named agent adapters keyed by name,
            or ``None`` if not provided.  Defaults to ``None``.
        context_reducer: The context reducer for chat primitives,
            or ``None`` for FIFO fallback.  Defaults to ``None``.
        circuit_breaker: The circuit breaker for provider fault tolerance,
            or ``None`` if not configured.  Defaults to ``None``.
        event_store: The event store for durable execution,
            or ``None`` if not configured.  Defaults to ``None``.
        mcp_registry: Registry of named MCP clients keyed by server name,
            or ``None`` if not provided.  Defaults to ``None``.
        tier_router: The tier router for model tier resolution,
            or ``None`` if not configured.  Defaults to ``None``.
        budget_enforcer: The budget enforcer for cost controls,
            or ``None`` if not configured.  Defaults to ``None``.
        approval_gate: The approval gate for HOTL approval flows,
            or ``None`` if not configured.  Defaults to ``None``.
        pii_tokenizer: The PII tokenizer for data protection,
            or ``None`` if not configured.  Defaults to ``None``.
        state_store: The state store for checkpoint persistence,
            or ``None`` if not configured.  Defaults to ``None``.
    """

    __slots__ = (
        "_llm_provider",
        "_lifecycle_hooks",
        "_execution_strategy",
        "_delegate_model",
        "_workflow_loader",
        "_registry",
        "_tool_registry",
        "_tracer",
        "_agent_adapter",
        "_agent_registry",
        "_context_reducer",
        "_circuit_breaker",
        "_event_store",
        "_mcp_registry",
        "_tier_router",
        "_budget_enforcer",
        "_approval_gate",
        "_pii_tokenizer",
        "_state_store",
    )

    def __init__(
        self,
        llm_provider: ILLMProvider | None = None,
        lifecycle_hooks: IHookManager | None = None,
        execution_strategy: IExecutionStrategy | None = None,
        delegate_model: str = "gpt-4o-mini",
        workflow_loader: Callable[[str], Workflow] | None = None,
        registry: PrimitiveRegistry | None = None,
        tool_registry: dict[str, Callable[..., Any]] | None = None,
        tracer: ITracer[Any] | None = None,
        agent_adapter: IAgentAdapter | None = None,
        agent_registry: dict[str, IAgentAdapter] | None = None,
        context_reducer: IContextReducer | None = None,
        circuit_breaker: ICircuitBreaker | None = None,
        event_store: IEventStore | None = None,
        mcp_registry: dict[str, Any] | None = None,
        tier_router: ITierRouter | None = None,
        budget_enforcer: IBudgetEnforcer | None = None,
        approval_gate: IApprovalGate | None = None,
        pii_tokenizer: IPIITokenizer | None = None,
        state_store: IStateStore | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._lifecycle_hooks = lifecycle_hooks
        self._execution_strategy = execution_strategy
        self._delegate_model = delegate_model
        self._workflow_loader = workflow_loader
        self._registry = registry
        self._tool_registry = tool_registry
        self._tracer = tracer
        self._agent_adapter = agent_adapter
        self._agent_registry = agent_registry
        self._context_reducer = context_reducer
        self._circuit_breaker = circuit_breaker
        self._event_store = event_store
        self._mcp_registry = mcp_registry
        self._tier_router = tier_router
        self._budget_enforcer = budget_enforcer
        self._approval_gate = approval_gate
        self._pii_tokenizer = pii_tokenizer
        self._state_store = state_store

    @property
    def llm_provider(self) -> ILLMProvider | None:
        """The LLM provider adapter, or ``None`` if not configured."""
        return self._llm_provider

    @property
    def lifecycle_hooks(self) -> IHookManager | None:
        """Hook manager for lifecycle notifications, or ``None``."""
        return self._lifecycle_hooks

    @property
    def execution_strategy(self) -> IExecutionStrategy | None:
        """Return the injected execution strategy, or None to use default."""
        return self._execution_strategy

    @property
    def delegate_model(self) -> str:
        """Return the model name used for delegate step LLM calls."""
        return self._delegate_model

    @property
    def workflow_loader(self) -> Callable[[str], Workflow] | None:
        """Callable that loads a sub-workflow by name, or ``None``."""
        return self._workflow_loader

    @property
    def registry(self) -> PrimitiveRegistry | None:
        """The primitive registry, or ``None`` if not provided."""
        return self._registry

    @property
    def tool_registry(self) -> dict[str, Callable[..., Any]] | None:
        """Registry of tool callables, or ``None`` if not provided."""
        return self._tool_registry

    @property
    def tracer(self) -> ITracer[Any] | None:
        """The observability tracer, or ``None`` if not configured."""
        return self._tracer

    @property
    def agent_adapter(self) -> IAgentAdapter | None:
        """The default agent adapter, or ``None`` if not configured."""
        return self._agent_adapter

    @property
    def agent_registry(self) -> dict[str, IAgentAdapter] | None:
        """Registry of named agent adapters, or ``None`` if not provided."""
        return self._agent_registry

    @property
    def context_reducer(self) -> IContextReducer | None:
        """The context reducer for chat primitives, or ``None`` for FIFO fallback."""
        return self._context_reducer

    @property
    def circuit_breaker(self) -> ICircuitBreaker | None:
        """The circuit breaker for provider fault tolerance, or ``None`` if not configured."""
        return self._circuit_breaker

    @property
    def event_store(self) -> IEventStore | None:
        """The event store for durable execution, or ``None`` if not configured."""
        return self._event_store

    @property
    def mcp_registry(self) -> dict[str, Any] | None:
        """Registry of named MCP clients, or ``None`` if not configured."""
        return self._mcp_registry

    @property
    def tier_router(self) -> ITierRouter | None:
        """The tier router for model tier resolution, or ``None`` if not configured."""
        return self._tier_router

    @property
    def budget_enforcer(self) -> IBudgetEnforcer | None:
        """The budget enforcer for cost controls, or ``None`` if not configured."""
        return self._budget_enforcer

    @property
    def approval_gate(self) -> IApprovalGate | None:
        """The approval gate for HOTL approval flows, or ``None`` if not configured."""
        return self._approval_gate

    @property
    def pii_tokenizer(self) -> IPIITokenizer | None:
        """The PII tokenizer for data protection, or ``None`` if not configured."""
        return self._pii_tokenizer

    @property
    def state_store(self) -> IStateStore | None:
        """The state store for checkpoint persistence, or ``None`` if not configured."""
        return self._state_store


_log = logging.getLogger(__name__)


class InterruptibleContext:
    """Mixin providing checkpoint/resume capabilities for execution contexts.

    Adds ``serialize()`` / ``restore()`` methods and a ``suspended`` flag so
    that a running workflow can be paused, persisted, and later resumed.

    [Source: Architecture §4.7 — InterruptibleContext mixin]
    """

    suspended: bool = False

    def serialize(self) -> dict[str, Any]:
        """Capture context state into a JSON-serializable dictionary.

        Non-serializable metadata values (e.g. provider instances, callables)
        are silently excluded with a warning log.
        """
        safe_metadata: dict[str, Any] = {}
        for key, value in getattr(self, "metadata", {}).items():
            try:
                json.dumps(value)
                safe_metadata[key] = value
            except (TypeError, ValueError, OverflowError):
                _log.warning("Excluding non-serializable metadata key: %s", key)

        return {
            "workflow_id": getattr(self, "workflow_id", ""),
            "inputs": getattr(self, "inputs", {}),
            "step_results": getattr(self, "step_results", {}),
            "metadata": safe_metadata,
            "current_step_id": getattr(self, "current_step_id", None),
            "suspended": self.suspended,
            "event_store_position": getattr(self, "metadata", {}).get("_event_store_position", 0),
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Reconstruct context state from a previously serialized dictionary."""
        self.workflow_id = data.get("workflow_id", "")  # type: ignore[attr-defined]
        self.inputs = data.get("inputs", {})  # type: ignore[attr-defined]
        self.step_results = data.get("step_results", {})  # type: ignore[attr-defined]
        self.metadata = data.get("metadata", {})  # type: ignore[attr-defined]
        self.current_step_id = data.get("current_step_id")  # type: ignore[attr-defined]
        self.suspended = data.get("suspended", False)
        if "event_store_position" in data:
            self.metadata["_event_store_position"] = data["event_store_position"]  # type: ignore[attr-defined]

    async def checkpoint(self, state_store: IStateStore | None = None) -> None:
        """Serialize context state and optionally persist via a state store.

        Convenience wrapper around :meth:`serialize` + ``state_store.save()``.
        Callers can also invoke those two methods directly for more control.

        Args:
            state_store: Optional state store to persist the checkpoint.
                If ``None``, the method only serializes (no persistence).
        """
        serialized = self.serialize()
        if state_store is not None:
            workflow_id: str = getattr(self, "workflow_id", "")
            await state_store.save(workflow_id, serialized)

    async def restore_from_store(self, workflow_id: str, state_store: IStateStore) -> bool:
        """Load persisted state from a store and restore context.

        Convenience wrapper around ``state_store.load()`` + :meth:`restore`.

        Args:
            workflow_id: Identifier of the workflow whose state to load.
            state_store: The state store to load from.

        Returns:
            ``True`` if state was found and restored, ``False`` if no
            checkpoint exists for the given *workflow_id*.

        Raises:
            StateError: If the loaded state is corrupted (missing required keys).
        """
        loaded = await state_store.load(workflow_id)
        if loaded is None:
            return False
        # Validate required keys before restoring
        required_keys = {"workflow_id", "inputs", "step_results", "metadata"}
        if not required_keys.issubset(loaded.keys()):
            missing = required_keys - loaded.keys()
            raise StateError(
                STATE_CORRUPTED,
                f"Corrupted state for workflow {workflow_id!r}: missing keys {missing}",
            )
        self.restore(loaded)
        return True


class ExecutionContext(InterruptibleContext, BaseModel):
    """Mutable runtime context threaded through workflow execution.

    Carries workflow inputs, accumulated step results, and metadata that
    primitives and the executor can read and write during a run.  Inherits
    checkpoint/resume capabilities from :class:`InterruptibleContext`.

    Attributes:
        workflow_id: Identifier of the workflow being executed.
        inputs: User-supplied inputs for the workflow run.
        step_results: Results keyed by step id, populated during execution.
        metadata: Arbitrary runtime metadata.
        current_step_id: The id of the step currently being executed.
        suspended: When True the executor skips remaining steps gracefully.
        deps: Typed dependency container satisfying the
            :class:`~beddel.domain.ports.ExecutionDependencies` protocol.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    workflow_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    step_results: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    current_step_id: str | None = None
    deps: DefaultDependencies = Field(default_factory=DefaultDependencies)
    """Typed dependency container satisfying the ExecutionDependencies protocol."""


class EventType(StrEnum):
    """Observable event types emitted during workflow execution.

    Attributes:
        WORKFLOW_START: Emitted when a workflow run begins.
        WORKFLOW_END: Emitted when a workflow run completes.
        STEP_START: Emitted before a step executes.
        STEP_END: Emitted after a step completes.
        LLM_START: Emitted before an LLM call.
        LLM_END: Emitted after an LLM call completes.
        TEXT_CHUNK: Emitted for each streamed text chunk.
        ERROR: Emitted when an error occurs.
        RETRY: Emitted when a step retry is attempted.
        REFLECTION_START: Will be emitted when a reflection loop iteration begins (planned).
        REFLECTION_END: Will be emitted when a reflection loop iteration completes (planned).
        PARALLEL_START: Will be emitted when a parallel fan-out begins (planned).
        PARALLEL_END: Will be emitted when a parallel fan-in completes (planned).
    """

    WORKFLOW_START = "workflow_start"
    WORKFLOW_END = "workflow_end"
    STEP_START = "step_start"
    STEP_END = "step_end"
    LLM_START = "llm_start"
    LLM_END = "llm_end"
    TEXT_CHUNK = "text_chunk"
    ERROR = "error"
    RETRY = "retry"

    REFLECTION_START = "reflection_start"
    REFLECTION_END = "reflection_end"

    PARALLEL_START = "parallel_start"
    PARALLEL_END = "parallel_end"

    CIRCUIT_OPEN = "circuit_open"
    CIRCUIT_CLOSE = "circuit_close"

    GOAL_ATTEMPT = "goal_attempt"

    CHECKPOINT = "checkpoint"

    # --- Reserved for future epics (not yet implemented) ---
    # SUSPENDED = "suspended"      # Epic 5: emitted when execution is suspended for HITL
    # MEMORY_READ = "memory_read"  # Epic 6: emitted when episodic memory is accessed


class BeddelEvent(BaseModel):
    """An observable event emitted during workflow execution.

    Events are the primary mechanism for monitoring and logging workflow
    progress.  Each event carries a type, an optional step reference, and
    an arbitrary data payload.

    Attributes:
        event_type: The kind of event.
        step_id: The step that produced this event, if applicable.
        data: Arbitrary event payload.
        timestamp: Unix timestamp when the event was created.
    """

    event_type: EventType
    step_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class ToolDeclaration(BaseModel):
    """Declaration of a tool available to a workflow.

    Each declaration maps a logical tool name to a Python callable target
    using ``module:function`` format.  The parser resolves targets at parse
    time via ``importlib``.

    Note: ``allowed_tools`` (security allowlist) and ``tools`` (registration)
    are orthogonal concerns.  ``allowed_tools`` restricts which tools can
    execute; ``tools`` declares where tool code lives.  A tool can be
    registered via ``tools`` but blocked by ``allowed_tools``.

    Attributes:
        name: Logical name used to reference this tool in the workflow.
        target: Import path in ``module:function`` format.
    """

    name: str
    target: str


class Workflow(BaseModel):
    """Top-level workflow definition parsed from YAML.

    A workflow is an ordered sequence of steps with optional metadata and
    an input schema for validation.

    Attributes:
        id: Unique identifier for the workflow.
        name: Human-readable workflow name.
        description: Optional longer description.
        version: Semantic version string for the workflow definition.
        input_schema: Optional JSON-Schema-style dict for input validation.
        steps: Ordered list of steps to execute.
        metadata: Arbitrary metadata attached to the workflow.
        allowed_tools: Optional allowlist of tool names permitted in this
            workflow.  When ``None``, all registered tools are allowed.
        tools: Optional list of inline tool declarations.  Each entry maps
            a logical name to a ``module:function`` target resolved at parse
            time.  When ``None``, no inline tools are declared.
    """

    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    input_schema: dict[str, Any] | None = None
    steps: list[Step]
    metadata: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] | None = None
    tools: list[ToolDeclaration] | None = None


# ---------------------------------------------------------------------------
# Deferred model rebuilds — required for forward references and self-
# referential types (ExecutionStrategy → Step, Step → Step).
# ---------------------------------------------------------------------------
ExecutionStrategy.model_rebuild()
Step.model_rebuild()
