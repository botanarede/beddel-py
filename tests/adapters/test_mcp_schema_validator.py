"""Tests for MCP schema validation utility.

Validates ``validate_tool_arguments`` against various schema scenarios.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from beddel.adapters.mcp.schema_validator import validate_tool_arguments
from beddel.domain.errors import MCPError
from beddel.error_codes import MCP_SCHEMA_VALIDATION_FAILED

# ---------------------------------------------------------------------------
# Shared schema fixture
# ---------------------------------------------------------------------------

SAMPLE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
    },
    "required": ["name", "age"],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidateToolArguments:
    """Tests for validate_tool_arguments utility."""

    def test_valid_arguments_pass(self) -> None:
        """Valid arguments against a schema with required string and integer fields."""
        # Should not raise
        validate_tool_arguments({"name": "Alice", "age": 30}, SAMPLE_SCHEMA)

    def test_missing_required_field_raises(self) -> None:
        """Missing required field raises MCPError(MCP_SCHEMA_VALIDATION_FAILED)."""
        with pytest.raises(MCPError) as exc_info:
            validate_tool_arguments({"name": "Alice"}, SAMPLE_SCHEMA)
        assert exc_info.value.code == MCP_SCHEMA_VALIDATION_FAILED

    def test_wrong_type_raises(self) -> None:
        """Wrong type for a field raises MCPError(MCP_SCHEMA_VALIDATION_FAILED)."""
        with pytest.raises(MCPError) as exc_info:
            validate_tool_arguments({"name": "Alice", "age": "not-an-int"}, SAMPLE_SCHEMA)
        assert exc_info.value.code == MCP_SCHEMA_VALIDATION_FAILED

    def test_empty_schema_passes(self) -> None:
        """Empty schema {} accepts any arguments."""
        # Should not raise
        validate_tool_arguments({"anything": "goes", "count": 42}, {})

    def test_import_guard(self) -> None:
        """When jsonschema is unavailable, importing raises ImportError."""
        import importlib

        import beddel.adapters.mcp.schema_validator as mod

        with (
            patch.dict("sys.modules", {"jsonschema": None}),
            pytest.raises(ImportError, match="jsonschema not installed"),
        ):
            importlib.reload(mod)

        # Restore the module so other tests are not affected
        importlib.reload(mod)
