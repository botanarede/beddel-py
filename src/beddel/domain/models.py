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
import warnings
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from beddel.domain.ports import ILifecycleHook, ILLMProvider

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "BeddelEvent",
    "DefaultDependencies",
    "EventType",
    "ExecutionContext",
    "ExecutionStrategy",
    "InterruptibleContext",
    "RetryConfig",
    "Step",
    "StrategyType",
    "Workflow",
]


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


class DefaultDependencies:
    """Concrete dependency container for workflow execution.

    Provides typed access to the LLM provider and lifecycle hooks,
    satisfying the :class:`~beddel.domain.ports.ExecutionDependencies`
    protocol via structural subtyping.

    Args:
        llm_provider: The LLM provider adapter, or ``None`` if not configured.
        lifecycle_hooks: Lifecycle hooks to notify during execution.
            Defaults to an empty list when ``None`` is passed.
    """

    __slots__ = ("_llm_provider", "_lifecycle_hooks")

    def __init__(
        self,
        llm_provider: ILLMProvider | None = None,
        lifecycle_hooks: list[ILifecycleHook] | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._lifecycle_hooks = lifecycle_hooks if lifecycle_hooks is not None else []

    @property
    def llm_provider(self) -> ILLMProvider | None:
        """The LLM provider adapter, or ``None`` if not configured."""
        return self._llm_provider

    @property
    def lifecycle_hooks(self) -> list[ILifecycleHook]:
        """Lifecycle hooks to notify during workflow execution."""
        return self._lifecycle_hooks


class _DeprecatedMetadataDict(dict[str, Any]):
    """Warns on access to deprecated metadata keys."""

    _DEPRECATED_KEYS: frozenset[str] = frozenset({"llm_provider", "lifecycle_hooks"})

    def __getitem__(self, key: str) -> Any:
        if key in self._DEPRECATED_KEYS:
            warnings.warn(
                f"Access context.deps.{key} instead of context.metadata['{key}']. "
                "Direct metadata access is deprecated and will be removed in a "
                "future version.",
                DeprecationWarning,
                stacklevel=2,
            )
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Return value for *key* with a deprecation warning for migrated keys.

        Overrides :meth:`dict.get` to emit a :class:`DeprecationWarning`
        when callers access keys that have been migrated to
        ``context.deps``.
        """
        if key in self._DEPRECATED_KEYS and key in self:
            warnings.warn(
                f"Access context.deps.{key} instead of context.metadata['{key}']. "
                "Direct metadata access is deprecated and will be removed in a "
                "future version.",
                DeprecationWarning,
                stacklevel=2,
            )
        return super().get(key, default)


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
        }

    def restore(self, data: dict[str, Any]) -> None:
        """Reconstruct context state from a previously serialized dictionary."""
        self.workflow_id = data.get("workflow_id", "")  # type: ignore[attr-defined]
        self.inputs = data.get("inputs", {})  # type: ignore[attr-defined]
        self.step_results = data.get("step_results", {})  # type: ignore[attr-defined]
        self.metadata = data.get("metadata", {})  # type: ignore[attr-defined]
        self.current_step_id = data.get("current_step_id")  # type: ignore[attr-defined]
        self.suspended = data.get("suspended", False)


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
    metadata: dict[str, Any] = Field(default_factory=_DeprecatedMetadataDict)
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

    # --- Reserved for future epics (not yet implemented) ---
    # CHECKPOINT = "checkpoint"    # Epic 5: emitted when execution state is checkpointed
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
    """

    id: str
    name: str
    description: str = ""
    version: str = "1.0"
    input_schema: dict[str, Any] | None = None
    steps: list[Step]
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Deferred model rebuilds — required for forward references and self-
# referential types (ExecutionStrategy → Step, Step → Step).
# ---------------------------------------------------------------------------
ExecutionStrategy.model_rebuild()
Step.model_rebuild()
