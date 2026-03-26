"""Unit tests for beddel.primitives.llm module."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from _helpers import make_context, make_provider

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import DefaultDependencies, ExecutionContext
from beddel.domain.registry import PrimitiveRegistry
from beddel.error_codes import PRIM_TOOL_USE_MAX_ITERATIONS
from beddel.primitives import register_builtins
from beddel.primitives.llm import LLMPrimitive

# ---------------------------------------------------------------------------
# Tests: Single-turn invocation (AC-4)
# ---------------------------------------------------------------------------


class TestSingleTurnInvocation:
    """Tests for non-streaming LLM invocation (AC-4)."""

    async def test_complete_called_with_model_and_messages(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "prompt": "Say hi",
        }

        prim = LLMPrimitive()
        result = await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Say hi"}],
        )
        assert result == {"content": "Hello!"}

    async def test_temperature_and_max_tokens_forwarded(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "prompt": "Hello",
            "temperature": 0.7,
            "max_tokens": 256,
        }

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Hello"}],
            temperature=0.7,
            max_tokens=256,
        )

    async def test_no_optional_kwargs_when_absent(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        # Called with positional args only, no kwargs
        _, kwargs = provider.complete.call_args
        assert kwargs == {}

    async def test_empty_messages_when_no_prompt_or_messages(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"model": "gpt-4o"}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with("gpt-4o", [])


# ---------------------------------------------------------------------------
# Tests: Prompt config key (subtask 6.3)
# ---------------------------------------------------------------------------


class TestPromptConfigKey:
    """Tests for the 'prompt' config key conversion to messages."""

    async def test_prompt_converted_to_user_message(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "What is 2+2?"}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert messages == [{"role": "user", "content": "What is 2+2?"}]

    async def test_prompt_takes_precedence_over_messages(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "prompt": "Use this",
            "messages": [{"role": "system", "content": "Ignore"}],
        }

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert messages == [{"role": "user", "content": "Use this"}]


# ---------------------------------------------------------------------------
# Tests: Messages config key (subtask 6.4)
# ---------------------------------------------------------------------------


class TestMessagesConfigKey:
    """Tests for the 'messages' config key pass-through."""

    async def test_messages_passed_through_directly(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        chat_messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        config = {"model": "gpt-4o", "messages": chat_messages}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        assert args[1] is chat_messages


# ---------------------------------------------------------------------------
# Tests: Missing llm_provider error (subtask 6.5, AC-7)
# ---------------------------------------------------------------------------


class TestMissingLLMProvider:
    """Tests for BEDDEL-PRIM-003 when llm_provider is absent."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        ctx = make_context(llm_provider=None)
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-003"

    async def test_error_message_mentions_llm_provider(self) -> None:
        ctx = make_context(llm_provider=None)
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert "llm_provider" in exc_info.value.message

    async def test_error_details_contain_step_id_and_primitive_type(self) -> None:
        ctx = make_context(llm_provider=None, step_id="my-step")
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.details == {
            "step_id": "my-step",
            "primitive_type": "llm",
        }


# ---------------------------------------------------------------------------
# Tests: Invalid llm_provider type (story 1.15, task 4)
# ---------------------------------------------------------------------------


class TestInvalidLLMProvider:
    """Tests for BEDDEL-PRIM-003 when llm_provider does not implement ILLMProvider."""

    async def test_raises_primitive_error_for_non_provider_object(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-test", current_step_id="step-1")
        # Inject a non-ILLMProvider object via a mock deps
        mock_deps = MagicMock()
        mock_deps.llm_provider = object()  # plain object, not ILLMProvider
        mock_deps.lifecycle_hooks = []
        ctx.deps = mock_deps
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-003"
        assert "ILLMProvider" in exc_info.value.message

    async def test_error_details_contain_provider_type(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-test", current_step_id="step-1")
        mock_deps = MagicMock()
        mock_deps.llm_provider = "not-a-provider"  # string, not ILLMProvider
        mock_deps.lifecycle_hooks = []
        ctx.deps = mock_deps
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.details["provider_type"] == "str"
        assert exc_info.value.details["primitive_type"] == "llm"


# ---------------------------------------------------------------------------
# Tests: Missing model error (subtask 6.6)
# ---------------------------------------------------------------------------


class TestMissingModel:
    """Tests for BEDDEL-PRIM-004 when model config key is absent."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"prompt": "Hi"}  # no model

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-004"

    async def test_error_message_mentions_model(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert "model" in exc_info.value.message

    async def test_error_details_contain_missing_key(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider, step_id="s2")
        config = {"prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.details == {
            "step_id": "s2",
            "primitive_type": "llm",
            "missing_key": "model",
        }


# ---------------------------------------------------------------------------
# Tests: Streaming mode (subtask 6.7, AC-5)
# ---------------------------------------------------------------------------


class TestStreamingMode:
    """Tests for streaming LLM invocation (AC-5)."""

    async def test_stream_returns_dict_with_stream_key(self) -> None:
        provider = make_provider(stream_chunks=["a", "b", "c"])
        ctx = make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Stream me", "stream": True}

        prim = LLMPrimitive()
        result = await prim.execute(config, ctx)

        assert "stream" in result

    async def test_stream_yields_expected_chunks(self) -> None:
        chunks = ["He", "llo", " world"]
        provider = make_provider(stream_chunks=chunks)
        ctx = make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Stream me", "stream": True}

        prim = LLMPrimitive()
        result = await prim.execute(config, ctx)

        collected: list[str] = []
        async for chunk in result["stream"]:
            collected.append(chunk)

        assert collected == chunks

    async def test_stream_calls_provider_stream_not_complete(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Stream", "stream": True}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        provider.stream.assert_called_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Stream"}],
        )
        provider.complete.assert_not_awaited()

    async def test_stream_forwards_kwargs(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "prompt": "Stream",
            "stream": True,
            "temperature": 0.5,
            "max_tokens": 100,
        }

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        provider.stream.assert_called_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Stream"}],
            temperature=0.5,
            max_tokens=100,
        )

    async def test_non_streaming_when_stream_false(self) -> None:
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Hi", "stream": False}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once()
        provider.stream.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: register_builtins (subtask 6.8, AC-3)
# ---------------------------------------------------------------------------


class TestRegisterBuiltins:
    """Tests for register_builtins() populating the registry."""

    def test_registers_llm_primitive(self) -> None:
        registry = PrimitiveRegistry()

        register_builtins(registry)

        assert registry.has("llm")

    def test_registered_llm_is_llm_primitive_instance(self) -> None:
        registry = PrimitiveRegistry()

        register_builtins(registry)

        assert isinstance(registry.get("llm"), LLMPrimitive)


# ---------------------------------------------------------------------------
# Tests: Tool-use loop integration (Story 4.0f, Task 4)
# ---------------------------------------------------------------------------


class TestLLMToolUseLoop:
    """Tests for tool-use loop wiring in LLMPrimitive.execute()."""

    @staticmethod
    def _tool_call_response(
        tool_name: str = "get_weather",
        arguments: str = '{"city": "London"}',
        call_id: str = "call_abc",
    ) -> dict[str, Any]:
        return {
            "content": None,
            "finish_reason": "tool_calls",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": arguments},
                }
            ],
        }

    @staticmethod
    def _text_response(content: str = "Final answer") -> dict[str, Any]:
        return {"content": content, "finish_reason": "stop"}

    @staticmethod
    def _make_context_with_tools(
        provider: Any,
        registry: dict[str, Any] | None = None,
    ) -> ExecutionContext:
        if registry is None:
            registry = {"get_weather": lambda city: f"Sunny in {city}"}
        deps = DefaultDependencies(llm_provider=provider, tool_registry=registry)
        return ExecutionContext(workflow_id="test", current_step_id="s1", deps=deps)

    async def test_execute_with_tool_use_loop(self) -> None:
        """Config has tool_schemas; provider returns tool_calls then text."""
        provider = make_provider()
        # Loop calls complete: tool_calls response, then text response
        provider.complete = AsyncMock(
            side_effect=[
                self._tool_call_response("get_weather", '{"city": "London"}', "call_1"),
                self._text_response("It's sunny in London"),
            ]
        )
        ctx = self._make_context_with_tools(provider)
        config: dict[str, Any] = {
            "model": "gpt-4o",
            "prompt": "What's the weather?",
            "tool_schemas": [{"type": "function", "function": {"name": "get_weather"}}],
        }

        prim = LLMPrimitive()
        result = await prim.execute(config, ctx)

        assert result["content"] == "It's sunny in London"
        # Loop iteration 1 (tool_calls) + iteration 2 (text) = 2 calls
        assert provider.complete.await_count == 2

    async def test_execute_without_tool_schemas_unchanged(self) -> None:
        """No tool_schemas in config — existing behaviour, no loop."""
        provider = make_provider()
        ctx = make_context(llm_provider=provider)
        config: dict[str, Any] = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        result = await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Hi"}],
        )
        assert result == {"content": "Hello!"}

    async def test_execute_tool_schemas_no_tool_calls(self) -> None:
        """Config has tool_schemas but provider returns text-only (no tool_calls)."""
        provider = make_provider(complete_return={"content": "No tools needed"})
        ctx = self._make_context_with_tools(provider)
        config: dict[str, Any] = {
            "model": "gpt-4o",
            "prompt": "Hello",
            "tool_schemas": [{"type": "function", "function": {"name": "get_weather"}}],
        }

        prim = LLMPrimitive()
        result = await prim.execute(config, ctx)

        assert result["content"] == "No tools needed"
        # Loop calls complete once, sees no tool_calls, returns immediately
        provider.complete.assert_awaited_once()

    async def test_execute_tool_use_max_iterations(self) -> None:
        """Config has tool_schemas and max_tool_iterations=1; always returns tool_calls."""
        provider = make_provider()
        provider.complete = AsyncMock(
            return_value=self._tool_call_response("get_weather", '{"city": "X"}', "call_loop"),
        )
        ctx = self._make_context_with_tools(provider)
        config: dict[str, Any] = {
            "model": "gpt-4o",
            "prompt": "Loop forever",
            "tool_schemas": [{"type": "function", "function": {"name": "get_weather"}}],
            "max_tool_iterations": 1,
        }

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == PRIM_TOOL_USE_MAX_ITERATIONS
