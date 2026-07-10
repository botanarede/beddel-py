"""Structured error code catalog and exception hierarchy for Beddel SDK.

All errors raised by the SDK are subclasses of :class:`BeddelError` and carry
a structured error code with the ``BEDDEL-`` prefix, a human-readable message,
and an optional details dict for machine-consumable context.

Error code prefixes by domain:

=================  ============================
Prefix             Domain
=================  ============================
``BEDDEL-PARSE-``  YAML parsing and validation
``BEDDEL-RESOLVE-``  Variable resolution
``BEDDEL-EXEC-``   Workflow execution
``BEDDEL-PRIM-``   Primitive execution
``BEDDEL-ADAPT-``  Adapter errors
``BEDDEL-AGENT-``  Agent adapter errors
``BEDDEL-APPROVAL-``  Approval gate errors
``BEDDEL-DURABLE-``  Durable execution errors
``BEDDEL-MCP-``  MCP integration errors
``BEDDEL-KIT-``  Kit manifest errors
``BEDDEL-PII-``  PII tokenization errors
``BEDDEL-STATE-``  State persistence errors
``BEDDEL-MEMORY-``  Episodic memory errors
``BEDDEL-KNOWLEDGE-``  Knowledge architecture errors
``BEDDEL-DECISION-``  Decision-centric runtime errors
``BEDDEL-COORD-``  Multi-agent coordination errors
``BEDDEL-EVENT-``  Event-driven execution errors
``BEDDEL-SKILL-``  Skill composition errors
=================  ============================
"""

from __future__ import annotations

from typing import Any

from beddel.error_codes import STATE_CONFLICT

__all__ = [
    "BeddelError",
    "ParseError",
    "ResolveError",
    "ExecutionError",
    "PrimitiveError",
    "AdapterError",
    "AgentError",
    "ApprovalError",
    "TracingError",
    "DurableError",
    "MCPError",
    "KitManifestError",
    "KitDependencyError",
    "BudgetError",
    "PIIError",
    "StateError",
    "StateConflictError",
    "MemoryError",
    "KnowledgeError",
    "DecisionError",
    "CoordinationError",
    "EventDrivenError",
    "SkillError",
]


class BeddelError(Exception):
    """Base exception for all Beddel SDK errors.

    Every error carries a structured code, a human-readable message, and an
    optional details dict.  The string representation is ``"{code}: {message}"``.

    Attributes:
        code: Structured error code (e.g. ``"BEDDEL-EXEC-001"``).
        message: Human-readable description of the error.
        details: Optional dict with machine-consumable context.
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}
        super().__init__(f"{code}: {message}")


class ParseError(BeddelError):
    """YAML parsing and validation errors.

    Error code prefix: ``BEDDEL-PARSE-``

    Raised when the SDK encounters invalid YAML syntax, schema violations,
    or structural problems in workflow definitions.

    Example codes:
        - ``BEDDEL-PARSE-001``: Invalid YAML syntax
    """


class ResolveError(BeddelError):
    """Variable resolution errors.

    Error code prefix: ``BEDDEL-RESOLVE-``

    Raised when template variables or references cannot be resolved during
    workflow preparation.

    Example codes:
        - ``BEDDEL-RESOLVE-001``: Unresolvable variable
    """


class ExecutionError(BeddelError):
    """Workflow execution errors.

    Error code prefix: ``BEDDEL-EXEC-``

    Raised when errors occur during workflow orchestration, step sequencing,
    or metadata handling.

    Example codes:
        - ``BEDDEL-EXEC-001``: Missing metadata key
    """


class PrimitiveError(BeddelError):
    """Primitive execution errors.

    Error code prefix: ``BEDDEL-PRIM-``

    Raised when a primitive (llm, chat, tool, etc.) fails during invocation
    or cannot be located in the registry.

    Example codes:
        - ``BEDDEL-PRIM-001``: Primitive not found
    """


class AdapterError(BeddelError):
    """Adapter errors.

    Error code prefix: ``BEDDEL-ADAPT-``

    Raised when an external adapter (LiteLLM, OpenTelemetry, etc.) encounters
    a failure such as authentication problems or connectivity issues.

    Example codes:
        - ``BEDDEL-ADAPT-001``: Provider authentication failure
    """


class TracingError(AdapterError):
    """Tracing operation errors.

    Error code prefix: ``BEDDEL-ADAPT-``

    Raised when an OpenTelemetry or other tracing adapter encounters a
    failure.  The ``fail_silent`` flag controls whether the caller should
    swallow the error (default) or re-raise it.

    Attributes:
        fail_silent: When ``True`` (default), callers should log a warning
            and continue execution.  When ``False``, callers should
            re-raise the error.

    Example codes:
        - ``BEDDEL-ADAPT-010``: Tracing failure
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        *,
        fail_silent: bool = True,
    ) -> None:
        super().__init__(code, message, details)
        self.fail_silent = fail_silent


class AgentError(BeddelError):
    """Agent adapter errors.

    Error code prefix: ``BEDDEL-AGENT-``

    Raised when an agent adapter encounters a failure such as missing
    configuration, execution errors, timeouts, or stream interruptions.

    Example codes:
        - ``BEDDEL-AGENT-700``: Agent adapter not configured
        - ``BEDDEL-AGENT-701``: Agent execution failed
        - ``BEDDEL-AGENT-702``: Agent execution timeout
        - ``BEDDEL-AGENT-703``: Agent stream interrupted
    """


class ApprovalError(BeddelError):
    """Approval gate errors. Error code prefix: BEDDEL-APPROVAL-"""


class DurableError(BeddelError):
    """Durable execution errors. Error code prefix: BEDDEL-DURABLE-"""


class MCPError(BeddelError):
    """MCP integration errors. Error code prefix: BEDDEL-MCP-"""


class KitManifestError(BeddelError):
    """Kit manifest errors. Error code prefix: BEDDEL-KIT-"""


class KitDependencyError(BeddelError):
    """Kit dependency errors — one or more pip packages are missing.

    Error code prefix: ``BEDDEL-KIT-``

    Attributes:
        missing_packages: List of dependency specifiers that are not installed.
    """

    def __init__(
        self,
        code: str,
        message: str,
        missing_packages: list[str],
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, details)
        self.missing_packages = missing_packages


class BudgetError(BeddelError):
    """Budget enforcement errors. Error code prefix: BEDDEL-BUDGET-"""


class PIIError(AdapterError):
    """PII tokenization errors. Error code prefix: BEDDEL-PII-"""


class StateError(BeddelError):
    """State persistence errors. Error code prefix: BEDDEL-STATE-"""


class StateConflictError(StateError):
    """Optimistic lock conflict on a versioned state write.

    Error code prefix: ``BEDDEL-STATE-`` (944)

    Raised by :class:`~beddel.domain.state.VersionedState` when a
    compare-and-swap write's ``expected_version`` does not match the
    key's current version — i.e. another writer updated the key
    concurrently.

    Attributes:
        key: The state key that had a version conflict.
        expected_version: The version the caller expected.
        actual_version: The version actually stored.
    """

    def __init__(self, key: str, expected: int, actual: int) -> None:
        super().__init__(
            STATE_CONFLICT,
            f"Version conflict for key '{key}': expected {expected}, got {actual}",
            details={"key": key, "expected_version": expected, "actual_version": actual},
        )
        self.key = key
        self.expected_version = expected
        self.actual_version = actual


class MemoryError(BeddelError):  # noqa: A001
    """Episodic memory errors. Error code prefix: BEDDEL-MEMORY-"""


class KnowledgeError(BeddelError):
    """Knowledge architecture errors. Error code prefix: BEDDEL-KNOWLEDGE-"""


class DecisionError(BeddelError):
    """Decision-centric runtime errors. Error code prefix: BEDDEL-DECISION-"""


class CoordinationError(BeddelError):
    """Multi-agent coordination errors. Error code prefix: BEDDEL-COORD-"""


class EventDrivenError(BeddelError):
    """Event-driven execution errors. Error code prefix: BEDDEL-EVENT-"""


class SkillError(BeddelError):
    """Skill composition errors. Error code prefix: BEDDEL-SKILL-"""
