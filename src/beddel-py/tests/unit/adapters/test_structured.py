"""Unit tests for the StructuredOutputHandler adapter."""

from __future__ import annotations

import json
from typing import Literal

import pytest
from pydantic import BaseModel

from beddel.adapters.structured import StructuredOutputHandler
from beddel.domain.models import ErrorCode, PrimitiveError

# ---------------------------------------------------------------------------
# Test Models
# ---------------------------------------------------------------------------


class Person(BaseModel):
    """Simple model for basic tests."""

    name: str
    age: int


class Address(BaseModel):
    """Nested model used by ComplexPerson."""

    street: str
    city: str


class ComplexPerson(BaseModel):
    """Complex model for AC 8 — nested, Optional, list, Literal."""

    name: str
    age: int | None
    tags: list[str]
    role: Literal["admin", "user"]
    address: Address


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def person_handler() -> StructuredOutputHandler[Person]:
    """Handler for the simple Person model."""
    return StructuredOutputHandler(Person)


@pytest.fixture
def complex_handler() -> StructuredOutputHandler[ComplexPerson]:
    """Handler for the ComplexPerson model."""
    return StructuredOutputHandler(ComplexPerson)


# ---------------------------------------------------------------------------
# 4.2 to_response_format() — simple model
# ---------------------------------------------------------------------------


def test_to_response_format_returns_litellm_compatible_dict(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """to_response_format() produces a LiteLLM-compatible JSON Schema dict."""
    # Act
    result = person_handler.to_response_format()

    # Assert — top-level structure
    assert result["type"] == "json_schema"
    assert "json_schema" in result

    json_schema = result["json_schema"]
    assert json_schema["name"] == "Person"
    assert json_schema["strict"] is True
    assert "schema" in json_schema


def test_to_response_format_schema_contains_model_properties(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """Schema includes 'name' (string) and 'age' (integer) properties."""
    # Act
    schema = person_handler.to_response_format()["json_schema"]["schema"]

    # Assert
    assert schema["type"] == "object"
    props = schema["properties"]
    assert "name" in props
    assert "age" in props
    assert props["name"]["type"] == "string"
    assert props["age"]["type"] == "integer"
    assert set(schema["required"]) == {"name", "age"}


# ---------------------------------------------------------------------------
# 4.3 to_response_format() — complex model (AC: 8)
# ---------------------------------------------------------------------------


def test_to_response_format_handles_optional_field(
    complex_handler: StructuredOutputHandler[ComplexPerson],
) -> None:
    """Schema supports Optional (int | None) fields via anyOf."""
    # Act
    schema = complex_handler.to_response_format()["json_schema"]["schema"]

    # Assert — age is int | None, Pydantic v2 uses anyOf
    age_schema = schema["properties"]["age"]
    assert "anyOf" in age_schema
    type_options = [opt.get("type") for opt in age_schema["anyOf"]]
    assert "integer" in type_options
    assert "null" in type_options


def test_to_response_format_handles_list_field(
    complex_handler: StructuredOutputHandler[ComplexPerson],
) -> None:
    """Schema supports list[str] fields."""
    # Act
    schema = complex_handler.to_response_format()["json_schema"]["schema"]

    # Assert
    tags_schema = schema["properties"]["tags"]
    assert tags_schema["type"] == "array"
    assert tags_schema["items"]["type"] == "string"


def test_to_response_format_handles_literal_field(
    complex_handler: StructuredOutputHandler[ComplexPerson],
) -> None:
    """Schema supports Literal types via enum."""
    # Act
    schema = complex_handler.to_response_format()["json_schema"]["schema"]

    # Assert
    role_schema = schema["properties"]["role"]
    assert "enum" in role_schema
    assert set(role_schema["enum"]) == {"admin", "user"}


def test_to_response_format_handles_nested_model(
    complex_handler: StructuredOutputHandler[ComplexPerson],
) -> None:
    """Schema supports nested Pydantic models via $ref or inline properties."""
    # Act
    schema = complex_handler.to_response_format()["json_schema"]["schema"]

    # Assert — nested model is referenced via $defs or inlined
    address_schema = schema["properties"]["address"]
    if "$ref" in address_schema:
        # Pydantic v2 uses $defs for nested models
        ref_name = address_schema["$ref"].split("/")[-1]
        assert ref_name in schema.get("$defs", {})
        nested = schema["$defs"][ref_name]
        assert "street" in nested["properties"]
        assert "city" in nested["properties"]
    else:
        # Inlined schema
        assert "street" in address_schema["properties"]
        assert "city" in address_schema["properties"]


# ---------------------------------------------------------------------------
# 4.4 parse_response() — happy path
# ---------------------------------------------------------------------------


def test_parse_response_valid_json_returns_model_instance(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """parse_response() with valid JSON returns a validated Pydantic instance."""
    # Arrange
    content = json.dumps({"name": "Alice", "age": 30})

    # Act
    result = person_handler.parse_response(content)

    # Assert
    assert isinstance(result, Person)
    assert result.name == "Alice"
    assert result.age == 30


def test_parse_response_complex_model_returns_instance(
    complex_handler: StructuredOutputHandler[ComplexPerson],
) -> None:
    """parse_response() with valid complex JSON returns a validated instance."""
    # Arrange
    content = json.dumps({
        "name": "Bob",
        "age": None,
        "tags": ["dev", "lead"],
        "role": "admin",
        "address": {"street": "123 Main St", "city": "Springfield"},
    })

    # Act
    result = complex_handler.parse_response(content)

    # Assert
    assert isinstance(result, ComplexPerson)
    assert result.name == "Bob"
    assert result.age is None
    assert result.tags == ["dev", "lead"]
    assert result.role == "admin"
    assert isinstance(result.address, Address)
    assert result.address.street == "123 Main St"
    assert result.address.city == "Springfield"


# ---------------------------------------------------------------------------
# 4.5 parse_response() — invalid JSON → PrimitiveError (AC: 4)
# ---------------------------------------------------------------------------


def test_parse_response_invalid_json_raises_primitive_error(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """parse_response() with invalid JSON raises PrimitiveError(BEDDEL-EXEC-001)."""
    # Arrange
    content = "not valid json {{"

    # Act & Assert
    with pytest.raises(PrimitiveError, match="Failed to parse LLM response as JSON") as exc_info:
        person_handler.parse_response(content)

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED
    assert "raw_content" in exc_info.value.details
    assert "error" in exc_info.value.details


def test_parse_response_invalid_json_chains_cause(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """PrimitiveError from invalid JSON chains the original JSONDecodeError."""
    # Arrange
    content = "{{broken"

    # Act & Assert
    with pytest.raises(PrimitiveError) as exc_info:
        person_handler.parse_response(content)

    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


def test_parse_response_empty_string_raises_primitive_error(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """parse_response() with empty string raises PrimitiveError(BEDDEL-EXEC-001)."""
    # Act & Assert
    with pytest.raises(PrimitiveError) as exc_info:
        person_handler.parse_response("")

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 4.6 parse_response() — schema mismatch → PrimitiveError (AC: 5)
# ---------------------------------------------------------------------------


def test_parse_response_schema_mismatch_raises_primitive_error(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """parse_response() with valid JSON but wrong schema raises PrimitiveError(BEDDEL-EXEC-001)."""
    # Arrange — valid JSON but missing required 'age' field
    content = json.dumps({"name": "Alice"})

    # Act & Assert
    with pytest.raises(
        PrimitiveError, match="LLM response does not conform to schema",
    ) as exc_info:
        person_handler.parse_response(content)

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED
    assert "validation_errors" in exc_info.value.details


def test_parse_response_wrong_type_raises_primitive_error(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """parse_response() with wrong field type raises PrimitiveError(BEDDEL-EXEC-001)."""
    # Arrange — 'age' should be int, not string
    content = json.dumps({"name": "Alice", "age": "not-a-number"})

    # Act & Assert
    with pytest.raises(PrimitiveError) as exc_info:
        person_handler.parse_response(content)

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED
    assert "validation_errors" in exc_info.value.details


def test_parse_response_schema_mismatch_chains_cause(
    person_handler: StructuredOutputHandler[Person],
) -> None:
    """PrimitiveError from schema mismatch chains the original ValidationError."""
    # Arrange
    content = json.dumps({"name": "Alice"})

    # Act & Assert
    with pytest.raises(PrimitiveError) as exc_info:
        person_handler.parse_response(content)

    assert exc_info.value.__cause__ is not None
