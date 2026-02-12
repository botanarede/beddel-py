"""Unit tests for beddel.primitives.llm module."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import ILLMProvider
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.llm import LLMPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    *,
    llm_provider: ILLMProvider | None = None,
    step_id: str | None = "step-1",
) -> ExecutionContext:
    """Build an ExecutionContext with an optional LLM provider in metadata."""
    metadata: dict[str, Any] = {}
    if llm_provider is not None:
        metadata["llm_provider"] = llm_provider
    return ExecutionContext(
        workflow_id="wf-test",
        metadata=metadata,
        current_step_id=step_id,
    )


def _make_provider(
    *,
    complete_return: dict[str, Any] | None = None,
    stream_chunks: list[str] | None = None,
) -> ILLMProvider:
    """Build a mock ILLMProvider with configurable return values."""
    provider = MagicMock(spec=ILLMProvider)
    provider.complete = AsyncMock(
        return_value=complete_return or {"content": "Hello!"},
    )

    async def _stream_gen(*_args: Any, **_kwargs: Any) -> AsyncGenerator[str, None]:
        for chunk in stream_chunks or ["He", "llo", "!"]:
            yield chunk

    provider.stream = MagicMock(side_effect=_stream_gen)
    return provider


# ---------------------------------------------------------------------------
# Tests: Single-turn invocation (AC-4)
# ---------------------------------------------------------------------------


class TestSingleTurnInvocation:
    """Tests for non-streaming LLM invocation (AC-4)."""

    async def test_complete_called_with_model_and_messages(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
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
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
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
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        # Called with positional args only, no kwargs
        _, kwargs = provider.complete.call_args
        assert kwargs == {}

    async def test_empty_messages_when_no_prompt_or_messages(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
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
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "What is 2+2?"}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert messages == [{"role": "user", "content": "What is 2+2?"}]

    async def test_prompt_takes_precedence_over_messages(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
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
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
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
        ctx = _make_context(llm_provider=None)
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-003"

    async def test_error_message_mentions_llm_provider(self) -> None:
        ctx = _make_context(llm_provider=None)
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert "llm_provider" in exc_info.value.message

    async def test_error_details_contain_step_id_and_primitive_type(self) -> None:
        ctx = _make_context(llm_provider=None, step_id="my-step")
        config = {"model": "gpt-4o", "prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.details == {
            "step_id": "my-step",
            "primitive_type": "llm",
        }


# ---------------------------------------------------------------------------
# Tests: Missing model error (subtask 6.6)
# ---------------------------------------------------------------------------


class TestMissingModel:
    """Tests for BEDDEL-PRIM-004 when model config key is absent."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {"prompt": "Hi"}  # no model

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-004"

    async def test_error_message_mentions_model(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {"prompt": "Hi"}

        prim = LLMPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert "model" in exc_info.value.message

    async def test_error_details_contain_missing_key(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider, step_id="s2")
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
        provider = _make_provider(stream_chunks=["a", "b", "c"])
        ctx = _make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Stream me", "stream": True}

        prim = LLMPrimitive()
        result = await prim.execute(config, ctx)

        assert "stream" in result

    async def test_stream_yields_expected_chunks(self) -> None:
        chunks = ["He", "llo", " world"]
        provider = _make_provider(stream_chunks=chunks)
        ctx = _make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Stream me", "stream": True}

        prim = LLMPrimitive()
        result = await prim.execute(config, ctx)

        collected: list[str] = []
        async for chunk in result["stream"]:
            collected.append(chunk)

        assert collected == chunks

    async def test_stream_calls_provider_stream_not_complete(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {"model": "gpt-4o", "prompt": "Stream", "stream": True}

        prim = LLMPrimitive()
        await prim.execute(config, ctx)

        provider.stream.assert_called_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Stream"}],
        )
        provider.complete.assert_not_awaited()

    async def test_stream_forwards_kwargs(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
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
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
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
