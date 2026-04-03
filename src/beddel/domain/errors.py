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
=================  ============================
"""

from __future__ import annotations

from typing import Any

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
