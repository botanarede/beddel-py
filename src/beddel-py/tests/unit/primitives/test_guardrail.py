"""Unit tests for the Guardrail primitive."""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    PrimitiveError,
)
from beddel.primitives.guardrail import guardrail_primitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx() -> ExecutionContext:
    """Minimal execution context (guardrail does not use it)."""
    return ExecutionContext()


# ---------------------------------------------------------------------------
# 4.2 Happy path: valid object input against object schema
# ---------------------------------------------------------------------------


async def test_valid_object_returns_input() -> None:
    """Valid object input matching schema returns the input as-is."""
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    data = {"name": "Alice"}
    result = await guardrail_primitive({"schema": schema, "input": data}, _ctx())
    assert result == data
    assert result is data  # passthrough, not a copy


# ---------------------------------------------------------------------------
# 4.3 Happy path: valid string input against string schema
# ---------------------------------------------------------------------------


async def test_valid_string_returns_input() -> None:
    """Valid string input matching schema returns the string as-is."""
    schema = {"type": "string"}
    data = "hello"
    result = await guardrail_primitive({"schema": schema, "input": data}, _ctx())
    assert result == "hello"


# ---------------------------------------------------------------------------
# 4.4 Validation failure raises PrimitiveError
# ---------------------------------------------------------------------------


async def test_validation_failure_raises() -> None:
    """Input violating schema raises PrimitiveError with BEDDEL-EXEC-001."""
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}, "required": ["age"]}
    data = {"age": "not-a-number"}

    with pytest.raises(PrimitiveError, match="Guardrail validation failed") as exc_info:
        await guardrail_primitive({"schema": schema, "input": data}, _ctx())

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 4.5 Validation failure details include message, path, schema_path
# ---------------------------------------------------------------------------


async def test_validation_failure_details() -> None:
    """PrimitiveError details include message, path, and schema_path."""
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "integer"}}},
    }
    data = {"items": [1, "bad", 3]}

    with pytest.raises(PrimitiveError) as exc_info:
        await guardrail_primitive({"schema": schema, "input": data}, _ctx())

    details = exc_info.value.details
    assert "message" in details
    assert "path" in details
    assert "schema_path" in details
    assert details["primitive"] == "guardrail"


# ---------------------------------------------------------------------------
# 4.6 Missing schema raises PrimitiveError
# ---------------------------------------------------------------------------


async def test_missing_schema_raises() -> None:
    """Missing 'schema' key raises PrimitiveError with BEDDEL-EXEC-001."""
    with pytest.raises(PrimitiveError, match="schema") as exc_info:
        await guardrail_primitive({"input": {"a": 1}}, _ctx())

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 4.7 Missing input raises PrimitiveError
# ---------------------------------------------------------------------------


async def test_missing_input_raises() -> None:
    """Missing 'input' key raises PrimitiveError with BEDDEL-EXEC-001."""
    with pytest.raises(PrimitiveError, match="input") as exc_info:
        await guardrail_primitive({"schema": {"type": "string"}}, _ctx())

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 4.8 on_fail="return_errors" with invalid input
# ---------------------------------------------------------------------------


async def test_on_fail_return_errors_invalid() -> None:
    """on_fail='return_errors' with invalid input returns error dict."""
    schema = {"type": "integer"}
    data = "not-an-int"

    result = await guardrail_primitive(
        {"schema": schema, "input": data, "on_fail": "return_errors"}, _ctx()
    )

    assert result["valid"] is False
    assert len(result["errors"]) == 1
    assert "message" in result["errors"][0]
    assert "path" in result["errors"][0]
    assert "schema_path" in result["errors"][0]


# ---------------------------------------------------------------------------
# 4.9 on_fail="return_errors" with valid input
# ---------------------------------------------------------------------------


async def test_on_fail_return_errors_valid() -> None:
    """on_fail='return_errors' with valid input returns success dict."""
    schema = {"type": "string"}
    data = "hello"

    result = await guardrail_primitive(
        {"schema": schema, "input": data, "on_fail": "return_errors"}, _ctx()
    )

    assert result == {"valid": True, "data": "hello"}


# ---------------------------------------------------------------------------
# 4.10 on_fail="raise" (explicit) behaves same as default
# ---------------------------------------------------------------------------


async def test_on_fail_raise_explicit() -> None:
    """Explicit on_fail='raise' behaves same as default (raises on failure)."""
    schema = {"type": "integer"}

    with pytest.raises(PrimitiveError):
        await guardrail_primitive(
            {"schema": schema, "input": "bad", "on_fail": "raise"}, _ctx()
        )


# ---------------------------------------------------------------------------
# 4.11 minLength constraint
# ---------------------------------------------------------------------------


async def test_min_length_constraint() -> None:
    """String shorter than minLength fails validation."""
    schema = {"type": "string", "minLength": 5}

    with pytest.raises(PrimitiveError, match="too short"):
        await guardrail_primitive({"schema": schema, "input": "hi"}, _ctx())


# ---------------------------------------------------------------------------
# 4.12 Nested object schema
# ---------------------------------------------------------------------------


async def test_nested_object_schema() -> None:
    """Validates nested object properties correctly."""
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
                "required": ["name"],
            }
        },
        "required": ["user"],
    }
    valid_data: dict[str, Any] = {"user": {"name": "Bob", "age": 30}}
    result = await guardrail_primitive({"schema": schema, "input": valid_data}, _ctx())
    assert result == valid_data

    invalid_data: dict[str, Any] = {"user": {"age": 30}}
    with pytest.raises(PrimitiveError):
        await guardrail_primitive({"schema": schema, "input": invalid_data}, _ctx())


# ---------------------------------------------------------------------------
# 4.13 Context is accepted but not used
# ---------------------------------------------------------------------------


async def test_context_accepted_but_unused() -> None:
    """Context parameter is accepted but the primitive does not use it."""
    ctx = ExecutionContext(
        workflow_id="test-wf",
        input={"should": "be-ignored"},
        metadata={"extra": "data"},
    )
    schema = {"type": "string"}
    result = await guardrail_primitive({"schema": schema, "input": "ok"}, ctx)
    assert result == "ok"
