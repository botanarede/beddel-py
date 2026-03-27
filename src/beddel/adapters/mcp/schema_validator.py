"""Schema validation utility for MCP tool arguments.

Validates tool arguments against a tool's ``inputSchema`` using the
``jsonschema`` library.  The ``jsonschema`` package is an optional
dependency (``pip install beddel[mcp]``).  Imports are guarded with
``try/except ImportError`` to provide a clear error message when the
extra is not installed.
"""

from __future__ import annotations

from typing import Any

from beddel.domain.errors import MCPError
from beddel.error_codes import MCP_SCHEMA_VALIDATION_FAILED

try:
    from jsonschema import ValidationError, validate
except ImportError as _imp_err:
    raise ImportError(
        "jsonschema not installed. Install with: pip install beddel[mcp]"
    ) from _imp_err

__all__ = ["validate_tool_arguments"]


def validate_tool_arguments(
    arguments: dict[str, Any],
    schema: dict[str, Any],
) -> None:
    """Validate tool arguments against a JSON Schema.

    Args:
        arguments: The tool arguments to validate.
        schema: The JSON Schema to validate against (typically the
            tool's ``inputSchema``).

    Raises:
        MCPError: ``BEDDEL-MCP-603`` when arguments fail validation.
    """
    try:
        validate(instance=arguments, schema=schema)
    except ValidationError as exc:
        raise MCPError(
            code=MCP_SCHEMA_VALIDATION_FAILED,
            message=f"Tool arguments failed schema validation: {exc.message}",
            details={
                "path": list(exc.absolute_path),
                "schema_path": list(exc.absolute_schema_path),
            },
        ) from exc
