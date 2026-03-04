"""Unit tests for beddel.primitives.chat module."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import DefaultDependencies, ExecutionContext
from beddel.domain.ports import ILLMProvider
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives import register_builtins
from beddel.primitives.chat import ChatPrimitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(
    *,
    llm_provider: ILLMProvider | None = None,
    step_id: str | None = "step-1",
) -> ExecutionContext:
    """Build an ExecutionContext with an optional LLM provider in deps."""
    return ExecutionContext(
        workflow_id="wf-test",
        deps=DefaultDependencies(llm_provider=llm_provider),
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
# Tests: Multi-turn conversation (subtask 3.2)
# ---------------------------------------------------------------------------


class TestMultiTurnConversation:
    """Tests for multi-turn message assembly: system + history + new user message."""

    async def test_system_and_messages_sent_to_provider(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "system": "You are helpful",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "More"},
            ],
        }

        prim = ChatPrimitive()
        result = await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
                {"role": "user", "content": "More"},
            ],
        )
        assert result == {"content": "Hello!"}

    async def test_system_prepended_to_messages(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "system": "Be concise",
            "messages": [{"role": "user", "content": "Hi"}],
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert messages[0] == {"role": "system", "content": "Be concise"}

    async def test_messages_only_without_system(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [
                {"role": "user", "content": "Hi"},
                {"role": "assistant", "content": "Hello"},
            ],
        )

    async def test_empty_messages_defaults_to_empty_list(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {"model": "gpt-4o"}

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with("gpt-4o", [])

    async def test_temperature_and_max_tokens_forwarded(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.7,
            "max_tokens": 256,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once_with(
            "gpt-4o",
            [{"role": "user", "content": "Hi"}],
            temperature=0.7,
            max_tokens=256,
        )


# ---------------------------------------------------------------------------
# Tests: Context windowing by max_messages (subtask 3.3)
# ---------------------------------------------------------------------------


class TestContextWindowingByMaxMessages:
    """Tests for max_messages trimming: oldest non-system dropped, system preserved."""

    async def test_trims_oldest_non_system_when_over_limit(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "user", "content": "msg2"},
                {"role": "user", "content": "msg3"},
                {"role": "user", "content": "msg4"},
                {"role": "user", "content": "msg5"},
            ],
            "max_messages": 3,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 3
        assert messages == [
            {"role": "user", "content": "msg3"},
            {"role": "user", "content": "msg4"},
            {"role": "user", "content": "msg5"},
        ]

    async def test_system_messages_always_preserved(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "system": "You are helpful",
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "user", "content": "msg2"},
                {"role": "user", "content": "msg3"},
                {"role": "user", "content": "msg4"},
                {"role": "user", "content": "msg5"},
            ],
            "max_messages": 2,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # System message preserved + last 2 non-system
        assert messages[0] == {"role": "system", "content": "You are helpful"}
        assert len(messages) == 3
        assert messages[1] == {"role": "user", "content": "msg4"}
        assert messages[2] == {"role": "user", "content": "msg5"}

    async def test_no_trimming_when_under_limit(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "msg1"},
                {"role": "user", "content": "msg2"},
                {"role": "user", "content": "msg3"},
            ],
            "max_messages": 10,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 3

    async def test_default_max_messages_is_50(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        # 5 messages, well under default 50 — all should be kept
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": f"msg{i}"} for i in range(5)],
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 5


# ---------------------------------------------------------------------------
# Tests: Context windowing by max_context_tokens (subtask 3.4)
# ---------------------------------------------------------------------------


class TestContextWindowingByMaxContextTokens:
    """Tests for token-based trimming of conversation history."""

    async def test_trims_oldest_when_over_token_budget(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        # Each "x" * 40 content => 40 // 4 = 10 tokens per message
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "x" * 40},  # 10 tokens
                {"role": "user", "content": "y" * 40},  # 10 tokens
                {"role": "user", "content": "z" * 40},  # 10 tokens
            ],
            "max_context_tokens": 20,  # budget for 2 messages only
            "max_messages": None,  # disable count limit
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # Oldest message dropped, last 2 kept (20 tokens fits 2 × 10)
        assert len(messages) == 2
        assert messages[0]["content"] == "y" * 40
        assert messages[1]["content"] == "z" * 40

    async def test_system_tokens_deducted_from_budget(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        # System: "s" * 20 => 20 // 4 = 5 tokens
        # Each user msg: "u" * 40 => 40 // 4 = 10 tokens
        # Budget = 15, system costs 5, leaves 10 for non-system (1 message)
        config = {
            "model": "gpt-4o",
            "system": "s" * 20,
            "messages": [
                {"role": "user", "content": "u" * 40},  # 10 tokens
                {"role": "user", "content": "v" * 40},  # 10 tokens
            ],
            "max_context_tokens": 15,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # System preserved + only last user message fits
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "s" * 20}
        assert messages[1]["content"] == "v" * 40

    async def test_no_trimming_when_under_budget(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "x" * 40},  # 10 tokens
                {"role": "user", "content": "y" * 40},  # 10 tokens
            ],
            "max_context_tokens": 1000,  # plenty of budget
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 2

    async def test_zero_budget_drops_all_non_system_messages(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "system": "Keep me",
            "messages": [
                {"role": "user", "content": "x" * 40},
                {"role": "user", "content": "y" * 40},
            ],
            "max_context_tokens": 0,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # Only system message survives — zero budget means no room for non-system
        assert len(messages) == 1
        assert messages[0] == {"role": "system", "content": "Keep me"}

    async def test_negative_budget_drops_all_non_system_messages(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        # System message alone exceeds budget
        config = {
            "model": "gpt-4o",
            "system": "s" * 100,  # 25 tokens, exceeds budget of 5
            "messages": [{"role": "user", "content": "hi"}],
            "max_context_tokens": 5,
            "max_messages": None,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        # System preserved, all non-system dropped (negative remaining budget)
        assert len(messages) == 1
        assert messages[0]["role"] == "system"

    async def test_unlimited_when_max_context_tokens_none(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        # Default max_context_tokens is None — no token trimming
        config = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "x" * 400},
                {"role": "user", "content": "y" * 400},
                {"role": "user", "content": "z" * 400},
            ],
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        args, _ = provider.complete.call_args
        messages = args[1]
        assert len(messages) == 3


# ---------------------------------------------------------------------------
# Tests: Streaming mode (subtask 3.5)
# ---------------------------------------------------------------------------


class TestStreamingMode:
    """Tests for streaming chat invocation returning async generator."""

    async def test_stream_returns_dict_with_stream_key(self) -> None:
        provider = _make_provider(stream_chunks=["a", "b", "c"])
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream me"}],
            "stream": True,
        }

        prim = ChatPrimitive()
        result = await prim.execute(config, ctx)

        assert "stream" in result

    async def test_stream_yields_expected_chunks(self) -> None:
        chunks = ["He", "llo", " world"]
        provider = _make_provider(stream_chunks=chunks)
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream me"}],
            "stream": True,
        }

        prim = ChatPrimitive()
        result = await prim.execute(config, ctx)

        collected: list[str] = []
        async for chunk in result["stream"]:
            collected.append(chunk)

        assert collected == chunks

    async def test_stream_calls_provider_stream_not_complete(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream"}],
            "stream": True,
        }

        prim = ChatPrimitive()
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
            "messages": [{"role": "user", "content": "Stream"}],
            "stream": True,
            "temperature": 0.5,
            "max_tokens": 100,
        }

        prim = ChatPrimitive()
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
        config = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hi"}],
            "stream": False,
        }

        prim = ChatPrimitive()
        await prim.execute(config, ctx)

        provider.complete.assert_awaited_once()
        provider.stream.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Missing provider (subtask 3.6)
# ---------------------------------------------------------------------------


class TestMissingProvider:
    """Tests for BEDDEL-PRIM-003 when llm_provider is absent or invalid."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        ctx = _make_context(llm_provider=None)
        config = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-003"

    async def test_error_message_mentions_llm_provider(self) -> None:
        ctx = _make_context(llm_provider=None)
        config = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert "llm_provider" in exc_info.value.message

    async def test_error_details_contain_step_id_and_primitive_type(self) -> None:
        ctx = _make_context(llm_provider=None, step_id="my-step")
        config = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.details == {
            "step_id": "my-step",
            "primitive_type": "chat",
        }

    async def test_raises_for_invalid_provider_type(self) -> None:
        ctx = ExecutionContext(workflow_id="wf-test", current_step_id="step-1")
        mock_deps = MagicMock()
        mock_deps.llm_provider = object()  # plain object, not ILLMProvider
        mock_deps.lifecycle_hooks = []
        ctx.deps = mock_deps
        config = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-003"
        assert "ILLMProvider" in exc_info.value.message


# ---------------------------------------------------------------------------
# Tests: Missing model (subtask 3.7)
# ---------------------------------------------------------------------------


class TestMissingModel:
    """Tests for BEDDEL-PRIM-004 when model config key is absent."""

    async def test_raises_primitive_error_with_correct_code(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {"messages": [{"role": "user", "content": "Hi"}]}  # no model

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.code == "BEDDEL-PRIM-004"

    async def test_error_message_mentions_model(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider)
        config = {"messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert "model" in exc_info.value.message

    async def test_error_details_contain_missing_key(self) -> None:
        provider = _make_provider()
        ctx = _make_context(llm_provider=provider, step_id="s2")
        config = {"messages": [{"role": "user", "content": "Hi"}]}

        prim = ChatPrimitive()
        with pytest.raises(PrimitiveError) as exc_info:
            await prim.execute(config, ctx)

        assert exc_info.value.details == {
            "step_id": "s2",
            "primitive_type": "chat",
            "missing_key": "model",
        }


# ---------------------------------------------------------------------------
# Tests: register_builtins (subtask 3.8)
# ---------------------------------------------------------------------------


class TestRegisterBuiltins:
    """Tests for register_builtins() registering 'chat' in the registry."""

    def test_registers_chat_primitive(self) -> None:
        registry = PrimitiveRegistry()

        register_builtins(registry)

        assert registry.has("chat")

    def test_registered_chat_is_chat_primitive_instance(self) -> None:
        registry = PrimitiveRegistry()

        register_builtins(registry)

        assert isinstance(registry.get("chat"), ChatPrimitive)
