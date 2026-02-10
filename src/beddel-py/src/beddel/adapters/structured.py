"""Structured output handler — Pydantic model to LiteLLM response_format conversion."""

from __future__ import annotations

import json
import logging
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from beddel.domain.models import ErrorCode, PrimitiveError

logger = logging.getLogger("beddel.adapters.structured")

T = TypeVar("T", bound=BaseModel)


class StructuredOutputHandler(Generic[T]):
    """Handler for structured LLM output using Pydantic models.

    Converts Pydantic models to LiteLLM's ``response_format`` parameter and
    parses LLM responses back into validated model instances.

    Supports nested Pydantic models, ``Optional`` fields, ``list[...]`` fields,
    and ``Literal`` types in schema generation.

    Args:
        model: A Pydantic model class to use for schema generation and validation.

    Example:
        >>> from pydantic import BaseModel
        >>> class Person(BaseModel):
        ...     name: str
        ...     age: int
        >>> handler = StructuredOutputHandler(Person)
        >>> response_format = handler.to_response_format()
        >>> person = handler.parse_response('{"name": "Alice", "age": 30}')
    """

    def __init__(self, model: type[T]) -> None:
        """Initialize the handler with a Pydantic model class.

        Args:
            model: The Pydantic model class to use for schema generation and validation.
        """
        self._model = model
        logger.debug(
            "StructuredOutputHandler initialized: model=%s",
            model.__name__,
        )

    def to_response_format(self) -> dict[str, Any]:
        """Generate LiteLLM-compatible response_format from the Pydantic model.

        Returns:
            A dict in LiteLLM's expected format:
            ``{"type": "json_schema", "json_schema": {"name": ..., "strict": True, "schema": ...}}``
        """
        schema = self._model.model_json_schema()
        model_name = self._model.__name__

        logger.debug(
            "Generated JSON schema: model=%s schema_keys=%s",
            model_name,
            list(schema.keys()),
        )

        response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": model_name,
                "strict": True,
                "schema": schema,
            },
        }

        return response_format

    def parse_response(self, content: str) -> T:
        """Parse raw LLM response content into a validated Pydantic model instance.

        Args:
            content: The raw JSON string from the LLM response.

        Returns:
            A validated instance of the Pydantic model.

        Raises:
            PrimitiveError: If the content is not valid JSON (BEDDEL-EXEC-001).
            PrimitiveError: If parsed JSON doesn't conform to schema (BEDDEL-EXEC-001).
        """
        model_name = self._model.__name__
        logger.debug(
            "Parsing response: model=%s content_length=%d",
            model_name,
            len(content),
        )

        # Step 1: Parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.debug(
                "JSON parse failed: model=%s error=%s content_snippet=%s",
                model_name,
                str(e),
                content[:100],
            )
            raise PrimitiveError(
                message="Failed to parse LLM response as JSON",
                code=ErrorCode.EXEC_STEP_FAILED,
                details={"raw_content": content[:200], "error": str(e)},
            ) from e

        # Step 2: Validate against Pydantic model
        try:
            instance = self._model.model_validate(data)
        except ValidationError as e:
            logger.debug(
                "Validation failed: model=%s errors=%s",
                model_name,
                e.errors(),
            )
            raise PrimitiveError(
                message="LLM response does not conform to schema",
                code=ErrorCode.EXEC_STEP_FAILED,
                details={"validation_errors": e.errors()},
            ) from e

        logger.debug(
            "Parse successful: model=%s",
            model_name,
        )

        return instance
