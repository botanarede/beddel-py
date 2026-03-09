"""Centralized error code registry for the Beddel SDK.

Every error raised by the SDK carries a machine-readable code from this
registry.  Codes follow the ``BEDDEL-{PREFIX}-{NNN}`` pattern and are
organised into non-overlapping numeric ranges by domain.

Ranges
------
==========  ========  ===========
Range       Prefix    Domain
==========  ========  ===========
100 – 199   PARSE     YAML parsing & validation
200 – 299   GUARD     Guardrail validation
300 – 399   PRIM      Primitive execution
400 – 499   ADAPT     Adapter errors
500 – 599   EXEC      Workflow execution
600 – 699   RESOLVE   Variable resolution
==========  ========  ===========
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Range boundary constants
# ---------------------------------------------------------------------------

PARSE_RANGE: tuple[int, int] = (100, 199)
"""YAML parsing & validation."""

GUARD_RANGE: tuple[int, int] = (200, 299)
"""Guardrail validation."""

PRIM_RANGE: tuple[int, int] = (300, 399)
"""Primitive execution."""

ADAPT_RANGE: tuple[int, int] = (400, 499)
"""Adapter errors."""

EXEC_RANGE: tuple[int, int] = (500, 599)
"""Workflow execution."""

RESOLVE_RANGE: tuple[int, int] = (600, 699)
"""Variable resolution."""

# ---------------------------------------------------------------------------
# Parser codes  (PARSE prefix, 100 range)
# ---------------------------------------------------------------------------

PARSE_INVALID_YAML: str = "BEDDEL-PARSE-001"
"""Invalid YAML syntax."""

PARSE_SCHEMA_VALIDATION: str = "BEDDEL-PARSE-002"
"""Schema validation failure."""

PARSE_MALFORMED_VARS: str = "BEDDEL-PARSE-003"
"""Malformed variable references."""

# ---------------------------------------------------------------------------
# Resolver codes  (RESOLVE prefix, 600 range)
# ---------------------------------------------------------------------------

RESOLVE_UNRESOLVABLE: str = "BEDDEL-RESOLVE-001"
"""Unresolvable variable."""

RESOLVE_CIRCULAR: str = "BEDDEL-RESOLVE-002"
"""Circular reference."""

RESOLVE_MAX_DEPTH: str = "BEDDEL-RESOLVE-003"
"""Max depth exceeded."""

# ---------------------------------------------------------------------------
# Guardrail codes  (GUARD prefix, 200 range)
# ---------------------------------------------------------------------------

GUARD_VALIDATION_FAILED: str = "BEDDEL-GUARD-201"
"""Validation failed, raise strategy."""

GUARD_INVALID_STRATEGY: str = "BEDDEL-GUARD-202"
"""Invalid strategy name."""

GUARD_MISSING_CONFIG: str = "BEDDEL-GUARD-203"
"""Missing required config keys."""

# ---------------------------------------------------------------------------
# Primitive codes  (PRIM prefix, 300 range)
# ---------------------------------------------------------------------------

PRIM_NOT_FOUND: str = "BEDDEL-PRIM-001"
"""Primitive/dependency not found."""

PRIM_INVALID_TYPE: str = "BEDDEL-PRIM-002"
"""Invalid primitive type."""

PRIM_MISSING_PROVIDER: str = "BEDDEL-PRIM-003"
"""Missing llm_provider (shared LLM utils)."""

PRIM_MISSING_MODEL: str = "BEDDEL-PRIM-004"
"""Missing model config key."""

PRIM_MISSING_TOOL_REGISTRY: str = "BEDDEL-PRIM-005"
"""Missing tool_registry."""

PRIM_INVALID_MESSAGE: str = "BEDDEL-PRIM-006"
"""Invalid message dict (missing required keys)."""

PRIM_OUTPUT_MISSING_TEMPLATE: str = "BEDDEL-PRIM-100"
"""Missing template for output-generator."""

PRIM_OUTPUT_UNSUPPORTED_FORMAT: str = "BEDDEL-PRIM-101"
"""Unsupported format for output-generator."""

PRIM_OUTPUT_FORMAT_FAILED: str = "BEDDEL-PRIM-102"
"""Output formatting failed."""

PRIM_MAX_DEPTH: str = "BEDDEL-PRIM-200"
"""Max call-agent nesting depth exceeded."""

PRIM_MISSING_WORKFLOW: str = "BEDDEL-PRIM-201"
"""Missing workflow config key."""

PRIM_TOOL_NOT_FOUND: str = "BEDDEL-PRIM-300"
"""Tool not found in registry."""

PRIM_TOOL_EXEC_FAILED: str = "BEDDEL-PRIM-301"
"""Tool execution failed."""

PRIM_TOOL_MISSING_CONFIG: str = "BEDDEL-PRIM-302"
"""Missing tool config key."""

# ---------------------------------------------------------------------------
# Adapter codes  (ADAPT prefix, 400 range)
# ---------------------------------------------------------------------------

ADAPT_AUTH_FAILURE: str = "BEDDEL-ADAPT-001"
"""Authentication failure."""

ADAPT_PROVIDER_ERROR: str = "BEDDEL-ADAPT-002"
"""Provider error."""

ADAPT_TIMEOUT: str = "BEDDEL-ADAPT-003"
"""Timeout/connection error."""

TRACING_FAILURE: str = "BEDDEL-ADAPT-010"
"""Tracing operation failed."""

# ---------------------------------------------------------------------------
# Execution codes  (EXEC prefix, 500 range)
# ---------------------------------------------------------------------------

EXEC_STEP_FAILED: str = "BEDDEL-EXEC-002"
"""Step failed."""

EXEC_RETRIES_EXHAUSTED: str = "BEDDEL-EXEC-003"
"""Retries exhausted."""

EXEC_NO_FALLBACK: str = "BEDDEL-EXEC-004"
"""No fallback defined."""

EXEC_TIMEOUT: str = "BEDDEL-EXEC-005"
"""Step timeout."""

EXEC_DELEGATE_FAILED: str = "BEDDEL-EXEC-010"
"""Delegate LLM call failed."""

EXEC_DELEGATE_INVALID: str = "BEDDEL-EXEC-011"
"""Delegate invalid action."""

# ---------------------------------------------------------------------------
# Integration codes
# ---------------------------------------------------------------------------

INTERNAL_SERVER_ERROR: str = "BEDDEL-INTERNAL-001"
"""Internal server error in FastAPI handler."""

# ---------------------------------------------------------------------------
# ALL_CODES registry — maps constant name → code string
# ---------------------------------------------------------------------------

ALL_CODES: dict[str, str] = {
    # Parser
    "PARSE_INVALID_YAML": PARSE_INVALID_YAML,
    "PARSE_SCHEMA_VALIDATION": PARSE_SCHEMA_VALIDATION,
    "PARSE_MALFORMED_VARS": PARSE_MALFORMED_VARS,
    # Resolver
    "RESOLVE_UNRESOLVABLE": RESOLVE_UNRESOLVABLE,
    "RESOLVE_CIRCULAR": RESOLVE_CIRCULAR,
    "RESOLVE_MAX_DEPTH": RESOLVE_MAX_DEPTH,
    # Guardrail
    "GUARD_VALIDATION_FAILED": GUARD_VALIDATION_FAILED,
    "GUARD_INVALID_STRATEGY": GUARD_INVALID_STRATEGY,
    "GUARD_MISSING_CONFIG": GUARD_MISSING_CONFIG,
    # Primitive
    "PRIM_NOT_FOUND": PRIM_NOT_FOUND,
    "PRIM_INVALID_TYPE": PRIM_INVALID_TYPE,
    "PRIM_MISSING_PROVIDER": PRIM_MISSING_PROVIDER,
    "PRIM_MISSING_MODEL": PRIM_MISSING_MODEL,
    "PRIM_MISSING_TOOL_REGISTRY": PRIM_MISSING_TOOL_REGISTRY,
    "PRIM_INVALID_MESSAGE": PRIM_INVALID_MESSAGE,
    "PRIM_OUTPUT_MISSING_TEMPLATE": PRIM_OUTPUT_MISSING_TEMPLATE,
    "PRIM_OUTPUT_UNSUPPORTED_FORMAT": PRIM_OUTPUT_UNSUPPORTED_FORMAT,
    "PRIM_OUTPUT_FORMAT_FAILED": PRIM_OUTPUT_FORMAT_FAILED,
    "PRIM_MAX_DEPTH": PRIM_MAX_DEPTH,
    "PRIM_MISSING_WORKFLOW": PRIM_MISSING_WORKFLOW,
    "PRIM_TOOL_NOT_FOUND": PRIM_TOOL_NOT_FOUND,
    "PRIM_TOOL_EXEC_FAILED": PRIM_TOOL_EXEC_FAILED,
    "PRIM_TOOL_MISSING_CONFIG": PRIM_TOOL_MISSING_CONFIG,
    # Adapter
    "ADAPT_AUTH_FAILURE": ADAPT_AUTH_FAILURE,
    "ADAPT_PROVIDER_ERROR": ADAPT_PROVIDER_ERROR,
    "ADAPT_TIMEOUT": ADAPT_TIMEOUT,
    "TRACING_FAILURE": TRACING_FAILURE,
    # Execution
    "EXEC_STEP_FAILED": EXEC_STEP_FAILED,
    "EXEC_RETRIES_EXHAUSTED": EXEC_RETRIES_EXHAUSTED,
    "EXEC_NO_FALLBACK": EXEC_NO_FALLBACK,
    "EXEC_TIMEOUT": EXEC_TIMEOUT,
    "EXEC_DELEGATE_FAILED": EXEC_DELEGATE_FAILED,
    "EXEC_DELEGATE_INVALID": EXEC_DELEGATE_INVALID,
    # Integration
    "INTERNAL_SERVER_ERROR": INTERNAL_SERVER_ERROR,
}
