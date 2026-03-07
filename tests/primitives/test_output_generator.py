"""Unit tests for beddel.primitives.output_generator module."""

from __future__ import annotations

import json
from typing import Any

import pytest
from _helpers import make_context

from beddel.domain.errors import PrimitiveError
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.output_generator import OutputGeneratorPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests: Template resolution (subtask 4.2)
# ---------------------------------------------------------------------------


class TestTemplateResolution:
    """Tests for $input and $stepResult variable resolution in templates."""

    async def test_resolves_input_variable(self) -> None:
        ctx = make_context(inputs={"name": "Alice"})
        config = {"template": "Hello $input.name"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "Hello Alice"

    async def test_resolves_step_result_variable(self) -> None:
        ctx = make_context(step_results={"analyze": {"summary": "All good"}})
        config = {"template": "Result: $stepResult.analyze.summary"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "Result: All good"

    async def test_resolves_multiple_variables(self) -> None:
        ctx = make_context(
            inputs={"user": "Bob"},
            step_results={"step1": {"score": "95"}},
        )
        config = {"template": "$input.user scored $stepResult.step1.score"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "Bob scored 95"

    async def test_full_input_reference_returns_dict(self) -> None:
        ctx = make_context(inputs={"a": 1, "b": 2})
        config = {"template": "$input.a", "format": "json"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert json.loads(result) == 1

    async def test_plain_string_without_variables_passes_through(self) -> None:
        ctx = make_context()
        config = {"template": "No variables here"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "No variables here"

    async def test_nested_input_path(self) -> None:
        ctx = make_context(inputs={"user": {"profile": {"name": "Carol"}}})
        config = {"template": "Hi $input.user.profile.name"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "Hi Carol"


# ---------------------------------------------------------------------------
# Tests: JSON format (subtask 4.3)
# ---------------------------------------------------------------------------


class TestJsonFormat:
    """Tests for JSON output formatting with json.dumps(indent=2)."""

    async def test_dict_formatted_as_indented_json(self) -> None:
        ctx = make_context(step_results={"s1": {"data": {"key": "value"}}})
        config = {
            "template": "$stepResult.s1.data",
            "format": "json",
        }

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == json.dumps({"key": "value"}, indent=2)

    async def test_default_indent_is_two(self) -> None:
        ctx = make_context(inputs={"items": [1, 2, 3]})
        config = {"template": "$input.items", "format": "json"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == json.dumps([1, 2, 3], indent=2)

    async def test_custom_indent(self) -> None:
        ctx = make_context(inputs={"items": [1, 2]})
        config = {"template": "$input.items", "format": "json", "indent": 4}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == json.dumps([1, 2], indent=4)

    async def test_string_value_serialized_as_json(self) -> None:
        ctx = make_context()
        config = {"template": "plain text", "format": "json"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == json.dumps("plain text", indent=2)

    async def test_ensure_ascii_false(self) -> None:
        ctx = make_context(inputs={"msg": "héllo"})
        config = {"template": "$input.msg", "format": "json"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert "héllo" in result
        assert "\\u" not in result


# ---------------------------------------------------------------------------
# Tests: Markdown format (subtask 4.4)
# ---------------------------------------------------------------------------


class TestMarkdownFormat:
    """Tests for markdown passthrough after variable resolution."""

    async def test_markdown_template_resolved_and_passed_through(self) -> None:
        ctx = make_context(inputs={"title": "Report"})
        config = {"template": "# $input.title", "format": "markdown"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "# Report"

    async def test_markdown_with_step_result(self) -> None:
        ctx = make_context(step_results={"gen": {"body": "Some content"}})
        config = {
            "template": "## Summary\n$stepResult.gen.body",
            "format": "markdown",
        }

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "## Summary\nSome content"

    async def test_markdown_plain_string_passes_through(self) -> None:
        ctx = make_context()
        config = {"template": "**bold** and _italic_", "format": "markdown"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "**bold** and _italic_"


# ---------------------------------------------------------------------------
# Tests: Text format / default (subtask 4.5)
# ---------------------------------------------------------------------------


class TestTextFormat:
    """Tests for default text format output."""

    async def test_text_is_default_format(self) -> None:
        ctx = make_context(inputs={"name": "Dave"})
        config = {"template": "Hello $input.name"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "Hello Dave"

    async def test_explicit_text_format(self) -> None:
        ctx = make_context(inputs={"name": "Eve"})
        config = {"template": "Hi $input.name", "format": "text"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "Hi Eve"

    async def test_text_format_stringifies_non_string_resolved_value(self) -> None:
        ctx = make_context(inputs={"count": 42})
        config = {"template": "$input.count", "format": "text"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        assert result == "42"

    async def test_text_format_dict_uses_json_serialization(self) -> None:
        """Dict values in text/markdown format use JSON (not Python repr)."""
        ctx = make_context(inputs={"data": {"key": "value", "num": 1}})
        config = {"template": "$input.data", "format": "text"}

        result = await OutputGeneratorPrimitive().execute(config, ctx)

        # Must be valid JSON with double quotes, not Python repr with single quotes
        parsed = json.loads(result)
        assert parsed == {"key": "value", "num": 1}
        assert '"key"' in result  # JSON double quotes, not Python single quotes


# ---------------------------------------------------------------------------
# Tests: Missing template (subtask 4.6)
# ---------------------------------------------------------------------------


class TestMissingTemplate:
    """Tests for BEDDEL-PRIM-100 error when template key is absent."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        ctx = make_context()
        config: dict[str, Any] = {"format": "text"}

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-100") as exc_info:
            await OutputGeneratorPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-100"

    async def test_error_message_mentions_template(self) -> None:
        ctx = make_context()
        config: dict[str, Any] = {}

        with pytest.raises(PrimitiveError) as exc_info:
            await OutputGeneratorPrimitive().execute(config, ctx)

        assert "template" in exc_info.value.message.lower()

    async def test_error_details_contain_primitive_and_step_id(self) -> None:
        ctx = make_context(step_id="my-step")
        config: dict[str, Any] = {"format": "json"}

        with pytest.raises(PrimitiveError) as exc_info:
            await OutputGeneratorPrimitive().execute(config, ctx)

        assert exc_info.value.details["primitive"] == "output-generator"
        assert exc_info.value.details["step_id"] == "my-step"


# ---------------------------------------------------------------------------
# Tests: Unsupported format (BEDDEL-PRIM-101)
# ---------------------------------------------------------------------------


class TestUnsupportedFormat:
    """Tests for BEDDEL-PRIM-101 error on invalid format values."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        ctx = make_context()
        config = {"template": "hello", "format": "xml"}

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-101") as exc_info:
            await OutputGeneratorPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-101"

    async def test_error_message_mentions_unsupported_format(self) -> None:
        ctx = make_context()
        config = {"template": "hello", "format": "yaml"}

        with pytest.raises(PrimitiveError) as exc_info:
            await OutputGeneratorPrimitive().execute(config, ctx)

        assert "yaml" in exc_info.value.message
        assert "Unsupported format" in exc_info.value.message

    async def test_error_details_contain_format_and_step_id(self) -> None:
        ctx = make_context(step_id="fmt-step")
        config = {"template": "hello", "format": "csv"}

        with pytest.raises(PrimitiveError) as exc_info:
            await OutputGeneratorPrimitive().execute(config, ctx)

        assert exc_info.value.details["format"] == "csv"
        assert exc_info.value.details["step_id"] == "fmt-step"


# ---------------------------------------------------------------------------
# Tests: JSON serialization error (BEDDEL-PRIM-102)
# ---------------------------------------------------------------------------


class TestJsonSerializationError:
    """Tests for BEDDEL-PRIM-102 error when JSON serialization fails."""

    async def test_non_serializable_value_raises_primitive_error(self) -> None:
        ctx = make_context(inputs={"obj": object()})
        config = {"template": "$input.obj", "format": "json"}

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-102") as exc_info:
            await OutputGeneratorPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-102"

    async def test_error_details_contain_format_and_original_error(self) -> None:
        ctx = make_context(inputs={"obj": {1, 2, 3}})
        config = {"template": "$input.obj", "format": "json"}

        with pytest.raises(PrimitiveError) as exc_info:
            await OutputGeneratorPrimitive().execute(config, ctx)

        assert exc_info.value.details["primitive"] == "output-generator"
        assert exc_info.value.details["format"] == "json"
        assert exc_info.value.details["original_error"]


# ---------------------------------------------------------------------------
# Tests: register_builtins (subtask 4.7)
# ---------------------------------------------------------------------------


class TestRegisterBuiltins:
    """Tests for output-generator registration via register_builtins."""

    def test_registers_output_generator_primitive(self) -> None:
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert registry.get("output-generator") is not None

    def test_registered_is_output_generator_instance(self) -> None:
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert isinstance(registry.get("output-generator"), OutputGeneratorPrimitive)
