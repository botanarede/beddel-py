"""Guardrail primitive — JSON Schema validation for workflow data."""

from __future__ import annotations

import logging
from typing import Any

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    PrimitiveError,
)

logger = logging.getLogger("beddel.primitives.guardrail")


async def guardrail_primitive(
    config: dict[str, Any],
    context: ExecutionContext,  # noqa: ARG001
) -> Any:
    """Validate input data against a JSON Schema definition.

    The VariableResolver has already substituted all variable references.
    This primitive validates config["input"] against config["schema"]
    and returns the input data on success.
    """
    if "schema" not in config:
        raise PrimitiveError(
            "guardrail requires a 'schema' key in config",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "guardrail", "hint": "Add schema field to config"},
        )

    if "input" not in config:
        raise PrimitiveError(
            "guardrail requires an 'input' key in config",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "guardrail", "hint": "Add input field to config"},
        )

    schema = config["schema"]
    input_data = config["input"]
    on_fail: str = config.get("on_fail", "raise")

    logger.debug(
        "Guardrail validating: schema_type=%s, input_type=%s",
        schema.get("type", "unknown") if isinstance(schema, dict) else "unknown",
        type(input_data).__name__,
    )

    try:
        validate(instance=input_data, schema=schema)
    except JsonSchemaValidationError as exc:
        error_detail: dict[str, Any] = {
            "message": exc.message,
            "path": list(exc.absolute_path),
            "schema_path": list(exc.absolute_schema_path),
        }
        logger.debug("Guardrail validation failed: %s", exc.message)
        if on_fail == "return_errors":
            return {"valid": False, "errors": [error_detail]}
        raise PrimitiveError(
            f"Guardrail validation failed: {exc.message}",
            code=ErrorCode.EXEC_STEP_FAILED,
            details={"primitive": "guardrail", **error_detail},
        ) from exc

    logger.debug("Guardrail validation passed: schema_type=%s", 
                 schema.get("type", "unknown") if isinstance(schema, dict) else "unknown")

    if on_fail == "return_errors":
        return {"valid": True, "data": input_data}
    return input_data
