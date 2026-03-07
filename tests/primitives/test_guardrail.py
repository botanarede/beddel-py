"""Unit tests for beddel.primitives.guardrail module."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import DefaultDependencies, ExecutionContext
from beddel.domain.ports import ILLMProvider
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.guardrail import GuardrailPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_SCHEMA: dict[str, Any] = {
    "fields": {
        "name": {"type": "str", "required": True},
        "age": {"type": "int"},
    },
}


def _make_context(
    *,
    inputs: dict[str, Any] | None = None,
    step_results: dict[str, Any] | None = None,
    step_id: str | None = "step-1",
    llm_provider: Any | None = None,
) -> ExecutionContext:
    """Build an ExecutionContext with optional inputs, step results, and provider."""
    return ExecutionContext(
        workflow_id="wf-test",
        inputs=inputs or {},
        step_results=step_results or {},
        current_step_id=step_id,
        deps=DefaultDependencies(llm_provider=llm_provider),
    )


def _make_provider(*, complete_return: dict[str, Any] | None = None) -> ILLMProvider:
    """Build a mock ILLMProvider with configurable return values."""
    provider = MagicMock(spec=ILLMProvider)
    provider.complete = AsyncMock(return_value=complete_return or {"content": "{}"})
    return provider


# ---------------------------------------------------------------------------
# Tests: Valid data passes through (subtask 5.2)
# ---------------------------------------------------------------------------


class TestValidDataPassesThrough:
    """Tests that valid data returns {"valid": True, "data": data}."""

    async def test_valid_dict_returns_valid_true(self) -> None:
        ctx = _make_context()
        config = {"data": {"name": "Alice", "age": 30}, "schema": SIMPLE_SCHEMA}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result == {"valid": True, "data": {"name": "Alice", "age": 30}}

    async def test_valid_data_with_optional_field_missing(self) -> None:
        ctx = _make_context()
        config = {"data": {"name": "Bob"}, "schema": SIMPLE_SCHEMA}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        assert result["data"] == {"name": "Bob"}

    async def test_empty_schema_fields_passes_any_data(self) -> None:
        ctx = _make_context()
        config = {"data": {"anything": "goes"}, "schema": {"fields": {}}}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result == {"valid": True, "data": {"anything": "goes"}}

    async def test_valid_data_with_explicit_raise_strategy(self) -> None:
        ctx = _make_context()
        config = {
            "data": {"name": "Carol", "age": 25},
            "schema": SIMPLE_SCHEMA,
            "strategy": "raise",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True

    async def test_extra_fields_are_silently_ignored(self) -> None:
        """Extra fields not in the schema are silently accepted (Pydantic default)."""
        ctx = _make_context()
        config = {
            "data": {"name": "Alice", "age": 30, "nickname": "Ally"},
            "schema": SIMPLE_SCHEMA,
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        assert result["data"] == {"name": "Alice", "age": 30, "nickname": "Ally"}


# ---------------------------------------------------------------------------
# Tests: Raise strategy (subtask 5.3)
# ---------------------------------------------------------------------------


class TestRaiseStrategy:
    """Tests that 'raise' strategy raises PrimitiveError("BEDDEL-GUARD-201")."""

    async def test_raises_on_invalid_data(self) -> None:
        ctx = _make_context()
        config = {"data": {"age": 30}, "schema": SIMPLE_SCHEMA, "strategy": "raise"}

        with pytest.raises(PrimitiveError, match="BEDDEL-GUARD-201") as exc_info:
            await GuardrailPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-GUARD-201"

    async def test_raise_is_default_strategy(self) -> None:
        ctx = _make_context()
        config = {"data": {"age": 30}, "schema": SIMPLE_SCHEMA}

        with pytest.raises(PrimitiveError, match="BEDDEL-GUARD-201"):
            await GuardrailPrimitive().execute(config, ctx)

    async def test_error_details_contain_errors_list(self) -> None:
        ctx = _make_context(step_id="guard-step")
        config = {"data": {"age": 30}, "schema": SIMPLE_SCHEMA, "strategy": "raise"}

        with pytest.raises(PrimitiveError) as exc_info:
            await GuardrailPrimitive().execute(config, ctx)

        assert "errors" in exc_info.value.details
        assert isinstance(exc_info.value.details["errors"], list)
        assert len(exc_info.value.details["errors"]) > 0

    async def test_error_details_contain_step_id(self) -> None:
        ctx = _make_context(step_id="guard-step")
        config = {"data": {"age": 30}, "schema": SIMPLE_SCHEMA, "strategy": "raise"}

        with pytest.raises(PrimitiveError) as exc_info:
            await GuardrailPrimitive().execute(config, ctx)

        assert exc_info.value.details["step_id"] == "guard-step"
        assert exc_info.value.details["primitive"] == "guardrail"


# ---------------------------------------------------------------------------
# Tests: Return errors strategy (subtask 5.4)
# ---------------------------------------------------------------------------


class TestReturnErrorsStrategy:
    """Tests that 'return_errors' returns {"valid": False, "errors": [...], "data": data}."""

    async def test_returns_errors_without_raising(self) -> None:
        ctx = _make_context()
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "return_errors",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) > 0
        assert result["data"] == {"age": 30}

    async def test_errors_list_contains_field_info(self) -> None:
        ctx = _make_context()
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "return_errors",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert any("name" in err for err in result["errors"])

    async def test_non_dict_data_returns_type_error(self) -> None:
        ctx = _make_context()
        config = {
            "data": "not a dict",
            "schema": SIMPLE_SCHEMA,
            "strategy": "return_errors",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert any("Expected dict" in err for err in result["errors"])


# ---------------------------------------------------------------------------
# Tests: Correct strategy — valid JSON string (subtask 5.5)
# ---------------------------------------------------------------------------


class TestCorrectStrategyValidJson:
    """Tests that 'correct' strategy parses valid JSON strings and validates."""

    async def test_valid_json_string_is_parsed_and_validated(self) -> None:
        ctx = _make_context()
        data = json.dumps({"name": "Alice", "age": 30})
        config = {"data": data, "schema": SIMPLE_SCHEMA, "strategy": "correct"}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        assert result["data"] == {"name": "Alice", "age": 30}

    async def test_valid_json_string_with_optional_field_only(self) -> None:
        ctx = _make_context()
        data = json.dumps({"name": "Bob"})
        config = {"data": data, "schema": SIMPLE_SCHEMA, "strategy": "correct"}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        assert result["data"] == {"name": "Bob"}


# ---------------------------------------------------------------------------
# Tests: Correct strategy — markdown-fenced JSON (subtask 5.6)
# ---------------------------------------------------------------------------


class TestCorrectStrategyMarkdownFenced:
    """Tests that 'correct' strategy strips markdown fences and parses JSON."""

    async def test_strips_json_fences_and_validates(self) -> None:
        ctx = _make_context()
        data = '```json\n{"name": "Alice", "age": 30}\n```'
        config = {"data": data, "schema": SIMPLE_SCHEMA, "strategy": "correct"}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        assert result["data"] == {"name": "Alice", "age": 30}

    async def test_strips_plain_fences_and_validates(self) -> None:
        ctx = _make_context()
        data = '```\n{"name": "Carol"}\n```'
        config = {"data": data, "schema": SIMPLE_SCHEMA, "strategy": "correct"}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        assert result["data"] == {"name": "Carol"}


# ---------------------------------------------------------------------------
# Tests: Correct strategy — unfixable data (subtask 5.7)
# ---------------------------------------------------------------------------


class TestCorrectStrategyUnfixable:
    """Tests that 'correct' strategy falls back to return_errors for unfixable data."""

    async def test_non_string_data_falls_back_to_return_errors(self) -> None:
        ctx = _make_context()
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "correct",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert isinstance(result["errors"], list)
        assert result["data"] == {"age": 30}

    async def test_invalid_json_string_falls_back(self) -> None:
        ctx = _make_context()
        config = {
            "data": "not valid json at all",
            "schema": SIMPLE_SCHEMA,
            "strategy": "correct",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert result["data"] == "not valid json at all"

    async def test_valid_json_but_schema_mismatch_falls_back(self) -> None:
        ctx = _make_context()
        data = json.dumps({"age": 30})
        config = {"data": data, "schema": SIMPLE_SCHEMA, "strategy": "correct"}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert any("name" in err for err in result["errors"])

    async def test_fenced_json_with_schema_mismatch_falls_back(self) -> None:
        ctx = _make_context()
        data = '```json\n{"age": 30}\n```'
        config = {"data": data, "schema": SIMPLE_SCHEMA, "strategy": "correct"}

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# Tests: Delegate strategy (subtask 5.8)
# ---------------------------------------------------------------------------


class TestDelegateStrategy:
    """Tests that 'delegate' strategy calls LLM and re-validates the response."""

    async def test_llm_fixes_data_successfully(self) -> None:
        corrected = json.dumps({"name": "Alice", "age": 30})
        provider = _make_provider(complete_return={"content": corrected})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        assert result["data"] == {"name": "Alice", "age": 30}
        provider.complete.assert_awaited_once()

    async def test_llm_called_with_correct_model(self) -> None:
        corrected = json.dumps({"name": "Bob"})
        provider = _make_provider(complete_return={"content": corrected})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
            "model": "custom-model",
        }

        await GuardrailPrimitive().execute(config, ctx)

        call_args = provider.complete.call_args
        assert call_args[0][0] == "custom-model"

    async def test_delegate_uses_default_model_from_deps(self) -> None:
        corrected = json.dumps({"name": "Carol"})
        provider = _make_provider(complete_return={"content": corrected})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
        }

        await GuardrailPrimitive().execute(config, ctx)

        call_args = provider.complete.call_args
        assert call_args[0][0] == "gpt-4o-mini"

    async def test_delegate_strips_markdown_fences_from_llm_response(self) -> None:
        fenced = '```json\n{"name": "Alice", "age": 25}\n```'
        provider = _make_provider(complete_return={"content": fenced})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        assert result["data"] == {"name": "Alice", "age": 25}


# ---------------------------------------------------------------------------
# Tests: Delegate strategy — missing provider (subtask 5.9)
# ---------------------------------------------------------------------------


class TestDelegateStrategyMissingProvider:
    """Tests that 'delegate' raises BEDDEL-PRIM-003 when llm_provider is missing."""

    async def test_raises_prim_003_without_provider(self) -> None:
        ctx = _make_context(llm_provider=None)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
        }

        with pytest.raises(PrimitiveError, match="BEDDEL-PRIM-003") as exc_info:
            await GuardrailPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-003"

    async def test_error_details_contain_primitive_type(self) -> None:
        ctx = _make_context(step_id="del-step", llm_provider=None)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
        }

        with pytest.raises(PrimitiveError) as exc_info:
            await GuardrailPrimitive().execute(config, ctx)

        assert exc_info.value.details["primitive_type"] == "guardrail"
        assert exc_info.value.details["step_id"] == "del-step"


# ---------------------------------------------------------------------------
# Tests: Delegate strategy — max_attempts exhausted (subtask 5.10)
# ---------------------------------------------------------------------------


class TestDelegateStrategyMaxAttempts:
    """Tests that 'delegate' falls back to return_errors after max_attempts."""

    async def test_exhausts_attempts_and_returns_errors(self) -> None:
        bad_response = json.dumps({"age": 99})
        provider = _make_provider(complete_return={"content": bad_response})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
            "max_attempts": 2,
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert isinstance(result["errors"], list)
        assert provider.complete.await_count == 2

    async def test_single_attempt_default(self) -> None:
        bad_response = json.dumps({"age": 99})
        provider = _make_provider(complete_return={"content": bad_response})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert provider.complete.await_count == 1

    async def test_non_json_llm_response_exhausts_attempts(self) -> None:
        provider = _make_provider(complete_return={"content": "I cannot fix this"})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
            "max_attempts": 2,
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is False
        assert any("not valid JSON" in err for err in result["errors"])
        assert provider.complete.await_count == 2


# ---------------------------------------------------------------------------
# Tests: Invalid strategy (subtask 5.11)
# ---------------------------------------------------------------------------


class TestInvalidStrategy:
    """Tests that an invalid strategy name raises BEDDEL-GUARD-202."""

    async def test_raises_prim_007_for_unknown_strategy(self) -> None:
        ctx = _make_context()
        config = {
            "data": {"name": "Alice"},
            "schema": SIMPLE_SCHEMA,
            "strategy": "explode",
        }

        with pytest.raises(PrimitiveError, match="BEDDEL-GUARD-202") as exc_info:
            await GuardrailPrimitive().execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-GUARD-202"

    async def test_error_message_mentions_strategy_name(self) -> None:
        ctx = _make_context()
        config = {
            "data": {"name": "Alice"},
            "schema": SIMPLE_SCHEMA,
            "strategy": "yolo",
        }

        with pytest.raises(PrimitiveError) as exc_info:
            await GuardrailPrimitive().execute(config, ctx)

        assert "yolo" in exc_info.value.message

    async def test_error_details_contain_strategy(self) -> None:
        ctx = _make_context(step_id="bad-step")
        config = {
            "data": {"name": "Alice"},
            "schema": SIMPLE_SCHEMA,
            "strategy": "nope",
        }

        with pytest.raises(PrimitiveError) as exc_info:
            await GuardrailPrimitive().execute(config, ctx)

        assert exc_info.value.details["strategy"] == "nope"
        assert exc_info.value.details["step_id"] == "bad-step"


# ---------------------------------------------------------------------------
# Tests: register_builtins (subtask 5.12)
# ---------------------------------------------------------------------------


class TestRegisterBuiltins:
    """Tests that register_builtins includes 'guardrail' in the registry."""

    def test_registers_guardrail_primitive(self) -> None:
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert registry.get("guardrail") is not None

    def test_registered_is_guardrail_instance(self) -> None:
        registry = PrimitiveRegistry()
        register_builtins(registry)

        assert isinstance(registry.get("guardrail"), GuardrailPrimitive)


# ---------------------------------------------------------------------------
# Tests: Delegate prompt template externalization (AC 6)
# ---------------------------------------------------------------------------


class TestDelegatePromptTemplate:
    """Tests for externalized delegate strategy prompt template (AC 6)."""

    async def test_default_template_is_used_when_no_override(self) -> None:
        """Default DELEGATE_PROMPT_TEMPLATE is used when no constructor override."""
        corrected = json.dumps({"name": "Alice", "age": 30})
        provider = _make_provider(complete_return={"content": corrected})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 30},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
        }

        result = await GuardrailPrimitive().execute(config, ctx)

        assert result["valid"] is True
        call_args = provider.complete.call_args
        prompt_msg = call_args[0][1][0]["content"]
        assert "Fix this data to match the schema:" in prompt_msg
        assert "Respond with ONLY the corrected JSON, no explanation." in prompt_msg

    async def test_custom_template_is_used_when_provided(self) -> None:
        """Constructor-provided template overrides the class default."""
        corrected = json.dumps({"name": "Bob", "age": 25})
        provider = _make_provider(complete_return={"content": corrected})
        ctx = _make_context(llm_provider=provider)
        config = {
            "data": {"age": 25},
            "schema": SIMPLE_SCHEMA,
            "strategy": "delegate",
        }
        custom_template = "CUSTOM: schema={schema} errors={errors} data={data}"

        prim = GuardrailPrimitive(delegate_prompt_template=custom_template)
        result = await prim.execute(config, ctx)

        assert result["valid"] is True
        call_args = provider.complete.call_args
        prompt_msg = call_args[0][1][0]["content"]
        assert prompt_msg.startswith("CUSTOM: schema=")
        assert "Fix this data" not in prompt_msg

    async def test_class_attribute_is_accessible(self) -> None:
        """DELEGATE_PROMPT_TEMPLATE class attribute is publicly accessible."""
        template = GuardrailPrimitive.DELEGATE_PROMPT_TEMPLATE
        assert "{schema}" in template
        assert "{errors}" in template
        assert "{data}" in template

    async def test_default_instance_uses_class_attribute(self) -> None:
        """Instance without override uses the class-level template."""
        prim = GuardrailPrimitive()
        assert prim._delegate_prompt_template == GuardrailPrimitive.DELEGATE_PROMPT_TEMPLATE
