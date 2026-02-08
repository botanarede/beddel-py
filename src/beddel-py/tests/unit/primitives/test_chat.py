"""Unit tests for the Chat primitive."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    LLMRequest,
    LLMResponse,
    Message,
    PrimitiveError,
    ProviderError,
    TokenUsage,
)
from beddel.primitives.chat import chat_primitive

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_provider() -> AsyncMock:
    """Create a mock ILLMProvider that returns a canned LLMResponse."""
    provider = AsyncMock()
    provider.complete.return_value = LLMResponse(
        content="Hello from chat!",
        model="test-model",
        usage=TokenUsage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )
    return provider


@pytest.fixture
def context_with_provider(mock_provider: AsyncMock) -> ExecutionContext:
    """ExecutionContext with a mock llm_provider injected."""
    return ExecutionContext(metadata={"llm_provider": mock_provider})


@pytest.fixture
def base_config() -> dict[str, Any]:
    """Minimal valid config for the chat primitive."""
    return {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
    }


# ---------------------------------------------------------------------------
# 3.2 Happy path
# ---------------------------------------------------------------------------


async def test_chat_happy_path(
    base_config: dict[str, Any],
    context_with_provider: ExecutionContext,
    mock_provider: AsyncMock,
) -> None:
    """Valid config with model + messages returns LLMResponse."""
    result = await chat_primitive(base_config, context_with_provider)

    assert isinstance(result, LLMResponse)
    assert result.content == "Hello from chat!"
    mock_provider.complete.assert_awaited_once()

    req: LLMRequest = mock_provider.complete.call_args[0][0]
    assert req.model == "test-model"
    assert len(req.messages) == 1
    assert req.messages[0] == Message(role="user", content="Hi")


# ---------------------------------------------------------------------------
# 3.3 System shorthand
# ---------------------------------------------------------------------------


async def test_system_shorthand_prepends_system_message(
    context_with_provider: ExecutionContext,
    mock_provider: AsyncMock,
) -> None:
    """Config with 'system' key prepends a system message."""
    config = {
        "model": "test-model",
        "system": "You are helpful.",
        "messages": [{"role": "user", "content": "Hi"}],
    }

    await chat_primitive(config, context_with_provider)

    req: LLMRequest = mock_provider.complete.call_args[0][0]
    assert len(req.messages) == 2
    assert req.messages[0] == Message(role="system", content="You are helpful.")
    assert req.messages[1] == Message(role="user", content="Hi")


# ---------------------------------------------------------------------------
# 3.4 History integration
# ---------------------------------------------------------------------------


async def test_history_inserts_between_system_and_new_messages(
    context_with_provider: ExecutionContext,
    mock_provider: AsyncMock,
) -> None:
    """History messages are inserted between system and new messages."""
    config = {
        "model": "test-model",
        "system": "You are helpful.",
        "history": [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "A programming language."},
        ],
        "messages": [{"role": "user", "content": "Tell me more."}],
    }

    await chat_primitive(config, context_with_provider)

    req: LLMRequest = mock_provider.complete.call_args[0][0]
    assert len(req.messages) == 4
    assert req.messages[0] == Message(role="system", content="You are helpful.")
    assert req.messages[1] == Message(role="user", content="What is Python?")
    assert req.messages[2] == Message(role="assistant", content="A programming language.")
    assert req.messages[3] == Message(role="user", content="Tell me more.")


# ---------------------------------------------------------------------------
# 3.5 History without system
# ---------------------------------------------------------------------------


async def test_history_without_system_comes_first(
    context_with_provider: ExecutionContext,
    mock_provider: AsyncMock,
) -> None:
    """Without system message, history messages come first."""
    config = {
        "model": "test-model",
        "history": [
            {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"},
        ],
        "messages": [{"role": "user", "content": "Follow-up"}],
    }

    await chat_primitive(config, context_with_provider)

    req: LLMRequest = mock_provider.complete.call_args[0][0]
    assert len(req.messages) == 3
    assert req.messages[0] == Message(role="user", content="Previous question")
    assert req.messages[1] == Message(role="assistant", content="Previous answer")
    assert req.messages[2] == Message(role="user", content="Follow-up")


# ---------------------------------------------------------------------------
# 3.6 Empty history
# ---------------------------------------------------------------------------


async def test_empty_history_behaves_same_as_no_history(
    base_config: dict[str, Any],
    context_with_provider: ExecutionContext,
    mock_provider: AsyncMock,
) -> None:
    """Config with history: [] behaves same as no history."""
    base_config["history"] = []

    await chat_primitive(base_config, context_with_provider)

    req: LLMRequest = mock_provider.complete.call_args[0][0]
    assert len(req.messages) == 1
    assert req.messages[0] == Message(role="user", content="Hi")


# ---------------------------------------------------------------------------
# 3.7 Optional fields passed through
# ---------------------------------------------------------------------------


async def test_optional_fields_passed_to_request(
    context_with_provider: ExecutionContext,
    mock_provider: AsyncMock,
) -> None:
    """temperature, max_tokens, response_format are forwarded to LLMRequest."""
    config = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
        "temperature": 0.2,
        "max_tokens": 100,
        "response_format": {"type": "json_object"},
    }

    await chat_primitive(config, context_with_provider)

    req: LLMRequest = mock_provider.complete.call_args[0][0]
    assert req.temperature == 0.2
    assert req.max_tokens == 100
    assert req.response_format == {"type": "json_object"}


# ---------------------------------------------------------------------------
# 3.8 Default values
# ---------------------------------------------------------------------------


async def test_default_values_when_optional_fields_missing(
    base_config: dict[str, Any],
    context_with_provider: ExecutionContext,
    mock_provider: AsyncMock,
) -> None:
    """Missing optional fields use LLMRequest defaults."""
    await chat_primitive(base_config, context_with_provider)

    req: LLMRequest = mock_provider.complete.call_args[0][0]
    assert req.temperature == 0.7
    assert req.max_tokens is None
    assert req.response_format is None


# ---------------------------------------------------------------------------
# 3.9 Missing llm_provider error
# ---------------------------------------------------------------------------


async def test_missing_provider_raises_primitive_error() -> None:
    """Missing llm_provider in context raises PrimitiveError BEDDEL-EXEC-001."""
    ctx = ExecutionContext(metadata={})
    config = {"model": "x", "messages": [{"role": "user", "content": "Hi"}]}

    with pytest.raises(PrimitiveError, match="llm_provider") as exc_info:
        await chat_primitive(config, ctx)

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.10 Provider failure wrapped in ProviderError
# ---------------------------------------------------------------------------


async def test_provider_failure_raises_provider_error(
    base_config: dict[str, Any],
    mock_provider: AsyncMock,
) -> None:
    """provider.complete() exception wrapped in ProviderError BEDDEL-PROVIDER-001."""
    mock_provider.complete.side_effect = RuntimeError("API down")
    ctx = ExecutionContext(metadata={"llm_provider": mock_provider})

    with pytest.raises(ProviderError, match="API down") as exc_info:
        await chat_primitive(base_config, ctx)

    assert exc_info.value.code == ErrorCode.PROVIDER_ERROR
    assert exc_info.value.__cause__ is not None


# ---------------------------------------------------------------------------
# 3.11 Provider field in config is ignored
# ---------------------------------------------------------------------------


async def test_provider_field_ignored_in_config(
    context_with_provider: ExecutionContext,
    mock_provider: AsyncMock,
) -> None:
    """The 'provider' field in config is not passed to LLMRequest."""
    config = {
        "provider": "google",
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hi"}],
    }

    await chat_primitive(config, context_with_provider)

    req: LLMRequest = mock_provider.complete.call_args[0][0]
    assert req.model == "test-model"
    assert not hasattr(req, "provider")
