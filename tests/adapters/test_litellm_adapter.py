"""Unit tests for beddel.adapters.litellm_adapter module."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from litellm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
    Timeout,
)

from beddel.adapters.litellm_adapter import LiteLLMAdapter
from beddel.domain.errors import AdapterError
from beddel.domain.ports import ILLMProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL = "openai/gpt-4o"
_MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": "Hello!"}]


def _make_completion_response(
    *,
    content: str = "Hello!",
    model: str = _MODEL,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    total_tokens: int = 15,
    finish_reason: str = "stop",
) -> MagicMock:
    """Build a mock litellm completion response object."""
    response = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    response.choices = [choice]
    response.model = model
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens
    response.usage = usage
    return response


def _make_stream_chunks(texts: list[str] | None = None) -> list[MagicMock]:
    """Build a list of mock streaming chunks."""
    chunks = []
    for text in texts or ["He", "llo", "!"]:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
        chunks.append(chunk)
    return chunks


async def _async_iter(items: list[Any]) -> Any:
    """Return an async iterator over *items*."""
    for item in items:
        yield item


def _make_auth_error() -> AuthenticationError:
    return AuthenticationError(
        message="Invalid API key",
        llm_provider="openai",
        model=_MODEL,
    )


def _make_api_error() -> APIError:
    return APIError(
        status_code=500,
        message="Internal server error",
        llm_provider="openai",
        model=_MODEL,
    )


def _make_rate_limit_error() -> RateLimitError:
    return RateLimitError(
        message="Rate limit exceeded",
        llm_provider="openai",
        model=_MODEL,
    )


def _make_bad_request_error() -> BadRequestError:
    return BadRequestError(
        message="Bad request",
        model=_MODEL,
        llm_provider="openai",
    )


def _make_timeout_error() -> Timeout:
    return Timeout(
        message="Request timed out",
        model=_MODEL,
        llm_provider="openai",
    )


def _make_connection_error() -> APIConnectionError:
    return APIConnectionError(
        message="Connection failed",
        llm_provider="openai",
        model=_MODEL,
    )


# ---------------------------------------------------------------------------
# Tests: Interface compliance (AC-1)
# ---------------------------------------------------------------------------


class TestInterfaceCompliance:
    """LiteLLMAdapter implements the ILLMProvider port interface."""

    def test_is_subclass_of_illm_provider(self) -> None:
        assert issubclass(LiteLLMAdapter, ILLMProvider)

    def test_instance_is_illm_provider(self) -> None:
        adapter = LiteLLMAdapter()
        assert isinstance(adapter, ILLMProvider)


# ---------------------------------------------------------------------------
# Tests: complete() (subtask 2.2)
# ---------------------------------------------------------------------------


class TestComplete:
    """Tests for LiteLLMAdapter.complete() — single-turn completion."""

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_forwards_model_and_messages(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()

        await adapter.complete(_MODEL, _MESSAGES)

        mock_acompletion.assert_awaited_once()
        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["model"] == _MODEL
        assert call_kwargs["messages"] == _MESSAGES

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_response_dict_structure(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.return_value = _make_completion_response(
            content="Hi there",
            model="openai/gpt-4o",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            finish_reason="stop",
        )
        adapter = LiteLLMAdapter()

        result = await adapter.complete(_MODEL, _MESSAGES)

        assert result["content"] == "Hi there"
        assert result["model"] == "openai/gpt-4o"
        assert result["usage"] == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
        assert result["finish_reason"] == "stop"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_forwards_extra_kwargs(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()

        await adapter.complete(_MODEL, _MESSAGES, temperature=0.7, max_tokens=256)

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["max_tokens"] == 256

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_usage_defaults_to_zero_when_none(self, mock_acompletion: AsyncMock) -> None:
        response = _make_completion_response()
        response.usage = None
        mock_acompletion.return_value = response
        adapter = LiteLLMAdapter()

        result = await adapter.complete(_MODEL, _MESSAGES)

        assert result["usage"] == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }


# ---------------------------------------------------------------------------
# Tests: stream() (subtask 2.3)
# ---------------------------------------------------------------------------


class TestStream:
    """Tests for LiteLLMAdapter.stream() — streaming completion."""

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_yields_text_chunks(self, mock_acompletion: AsyncMock) -> None:
        chunks = _make_stream_chunks(["He", "llo", "!"])
        mock_acompletion.return_value = _async_iter(chunks)
        adapter = LiteLLMAdapter()

        collected: list[str] = []
        async for text in adapter.stream(_MODEL, _MESSAGES):
            collected.append(text)

        assert collected == ["He", "llo", "!"]

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_calls_acompletion_with_stream_true(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.return_value = _async_iter([])
        adapter = LiteLLMAdapter()

        # Exhaust the generator
        async for _ in adapter.stream(_MODEL, _MESSAGES):
            pass

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["stream"] is True

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_skips_chunks_with_none_content(self, mock_acompletion: AsyncMock) -> None:
        chunk_with_content = MagicMock()
        chunk_with_content.choices = [MagicMock()]
        chunk_with_content.choices[0].delta.content = "Hello"

        chunk_none = MagicMock()
        chunk_none.choices = [MagicMock()]
        chunk_none.choices[0].delta.content = None

        mock_acompletion.return_value = _async_iter([chunk_none, chunk_with_content, chunk_none])
        adapter = LiteLLMAdapter()

        collected: list[str] = []
        async for text in adapter.stream(_MODEL, _MESSAGES):
            collected.append(text)

        assert collected == ["Hello"]

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_forwards_extra_kwargs(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.return_value = _async_iter([])
        adapter = LiteLLMAdapter()

        async for _ in adapter.stream(_MODEL, _MESSAGES, temperature=0.3):
            pass

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3


# ---------------------------------------------------------------------------
# Tests: API key resolution (subtasks 2.4, 2.5, 2.6)
# ---------------------------------------------------------------------------


class TestApiKeyResolution:
    """Tests for _resolve_api_key and its integration with complete()/stream()."""

    @pytest.mark.parametrize(
        ("model", "env_var"),
        [
            ("openai/gpt-4o", "OPENAI_API_KEY"),
            ("anthropic/claude-3", "ANTHROPIC_API_KEY"),
            ("gemini/gemini-2.0-flash", "GEMINI_API_KEY"),
            ("bedrock/anthropic.claude", "AWS_ACCESS_KEY_ID"),
            ("azure/gpt-4", "AZURE_API_KEY"),
            ("cohere/command", "COHERE_API_KEY"),
            ("mistral/mistral-large", "MISTRAL_API_KEY"),
        ],
    )
    def test_prefix_resolves_correct_env_var(self, model: str, env_var: str) -> None:
        adapter = LiteLLMAdapter()
        with patch.dict(os.environ, {env_var: "sk-test-key"}, clear=False):
            key = adapter._resolve_api_key(model)

        assert key == "sk-test-key"

    def test_no_prefix_defaults_to_openai_env_var(self) -> None:
        adapter = LiteLLMAdapter()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai"}, clear=False):
            key = adapter._resolve_api_key("gpt-4o")

        assert key == "sk-openai"

    def test_explicit_api_key_takes_precedence(self) -> None:
        adapter = LiteLLMAdapter()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}, clear=False):
            key = adapter._resolve_api_key("openai/gpt-4o", explicit_key="sk-explicit")

        assert key == "sk-explicit"

    def test_default_api_key_fallback(self) -> None:
        adapter = LiteLLMAdapter(default_api_key="sk-default")
        # Ensure no matching env var is set
        env = {k: "" for k in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]}
        with patch.dict(os.environ, env, clear=False):
            key = adapter._resolve_api_key("unknown-provider/model")

        assert key == "sk-default"

    def test_returns_none_when_no_key_found(self) -> None:
        adapter = LiteLLMAdapter()
        env = {k: "" for k in ["OPENAI_API_KEY"]}
        with patch.dict(os.environ, env, clear=False):
            key = adapter._resolve_api_key("unknown-provider/model")

        assert key is None

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_explicit_api_key_kwarg_forwarded_to_acompletion(
        self, mock_acompletion: AsyncMock
    ) -> None:
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()

        await adapter.complete(_MODEL, _MESSAGES, api_key="sk-explicit")

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-explicit"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_env_var_key_forwarded_to_acompletion(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-env"}, clear=False):
            await adapter.complete(_MODEL, _MESSAGES)

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-from-env"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_default_key_forwarded_to_acompletion(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter(default_api_key="sk-default")

        env = {k: "" for k in ["OPENAI_API_KEY"]}
        with patch.dict(os.environ, env, clear=False):
            await adapter.complete("unknown-provider/model", _MESSAGES)

        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-default"


# ---------------------------------------------------------------------------
# Tests: Error wrapping (subtasks 2.7, 2.8, 2.9)
# ---------------------------------------------------------------------------


class TestErrorWrappingComplete:
    """Tests for exception wrapping in complete()."""

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_auth_error_wrapped_as_adapt_001(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.side_effect = _make_auth_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            await adapter.complete(_MODEL, _MESSAGES)

        assert exc_info.value.code == "BEDDEL-ADAPT-001"
        assert exc_info.value.details["model"] == _MODEL

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_api_error_wrapped_as_adapt_002(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.side_effect = _make_api_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            await adapter.complete(_MODEL, _MESSAGES)

        assert exc_info.value.code == "BEDDEL-ADAPT-002"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_rate_limit_error_wrapped_as_adapt_002(
        self, mock_acompletion: AsyncMock
    ) -> None:
        mock_acompletion.side_effect = _make_rate_limit_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            await adapter.complete(_MODEL, _MESSAGES)

        assert exc_info.value.code == "BEDDEL-ADAPT-002"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_bad_request_error_wrapped_as_adapt_002(
        self, mock_acompletion: AsyncMock
    ) -> None:
        mock_acompletion.side_effect = _make_bad_request_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            await adapter.complete(_MODEL, _MESSAGES)

        assert exc_info.value.code == "BEDDEL-ADAPT-002"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_timeout_error_wrapped_as_adapt_003(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.side_effect = _make_timeout_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            await adapter.complete(_MODEL, _MESSAGES)

        assert exc_info.value.code == "BEDDEL-ADAPT-003"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_connection_error_wrapped_as_adapt_003(
        self, mock_acompletion: AsyncMock
    ) -> None:
        mock_acompletion.side_effect = _make_connection_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            await adapter.complete(_MODEL, _MESSAGES)

        assert exc_info.value.code == "BEDDEL-ADAPT-003"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_wrapped_error_preserves_original_cause(
        self, mock_acompletion: AsyncMock
    ) -> None:
        original = _make_auth_error()
        mock_acompletion.side_effect = original
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            await adapter.complete(_MODEL, _MESSAGES)

        assert exc_info.value.__cause__ is original


class TestErrorWrappingStream:
    """Tests for exception wrapping in stream() — both at call time and during iteration."""

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_auth_error_at_call_time(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.side_effect = _make_auth_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream(_MODEL, _MESSAGES):
                pass

        assert exc_info.value.code == "BEDDEL-ADAPT-001"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_timeout_error_at_call_time(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.side_effect = _make_timeout_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream(_MODEL, _MESSAGES):
                pass

        assert exc_info.value.code == "BEDDEL-ADAPT-003"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_api_error_at_call_time(self, mock_acompletion: AsyncMock) -> None:
        mock_acompletion.side_effect = _make_api_error()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream(_MODEL, _MESSAGES):
                pass

        assert exc_info.value.code == "BEDDEL-ADAPT-002"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_auth_error_during_iteration(self, mock_acompletion: AsyncMock) -> None:
        async def _exploding_iter() -> Any:
            yield _make_stream_chunks(["ok"])[0]
            raise _make_auth_error()

        mock_acompletion.return_value = _exploding_iter()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream(_MODEL, _MESSAGES):
                pass

        assert exc_info.value.code == "BEDDEL-ADAPT-001"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_timeout_error_during_iteration(self, mock_acompletion: AsyncMock) -> None:
        async def _exploding_iter() -> Any:
            raise _make_timeout_error()
            yield  # noqa: RET503 — unreachable yield makes this an async generator

        mock_acompletion.return_value = _exploding_iter()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream(_MODEL, _MESSAGES):
                pass

        assert exc_info.value.code == "BEDDEL-ADAPT-003"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_provider_error_during_iteration(self, mock_acompletion: AsyncMock) -> None:
        async def _exploding_iter() -> Any:
            raise _make_rate_limit_error()
            yield  # noqa: RET503 — unreachable yield makes this an async generator

        mock_acompletion.return_value = _exploding_iter()
        adapter = LiteLLMAdapter()

        with pytest.raises(AdapterError) as exc_info:
            async for _ in adapter.stream(_MODEL, _MESSAGES):
                pass

        assert exc_info.value.code == "BEDDEL-ADAPT-002"


# ---------------------------------------------------------------------------
# Tests: Tool calls passthrough (Story 4.0f, Task 2)
# ---------------------------------------------------------------------------


def _make_completion_response_with_tool_calls() -> MagicMock:
    """Build a mock litellm response with tool_calls on the message."""
    response = _make_completion_response(finish_reason="tool_calls")
    tc1 = MagicMock()
    tc1.id = "call_abc123"
    tc1.type = "function"
    tc1.function.name = "get_weather"
    tc1.function.arguments = '{"city": "London"}'
    response.choices[0].message.tool_calls = [tc1]
    return response


class TestToolCallsPassthrough:
    """Tests for tool_calls passthrough in LiteLLMAdapter.complete()."""

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_complete_with_tool_calls(self, mock_acompletion: AsyncMock) -> None:
        """Verify tool_calls are included in the response dict when present."""
        # Arrange
        mock_acompletion.return_value = _make_completion_response_with_tool_calls()
        adapter = LiteLLMAdapter()

        # Act
        result = await adapter.complete(_MODEL, _MESSAGES)

        # Assert
        assert "tool_calls" in result
        assert len(result["tool_calls"]) == 1
        tc = result["tool_calls"][0]
        assert tc["id"] == "call_abc123"
        assert tc["type"] == "function"
        assert tc["function"]["name"] == "get_weather"
        assert tc["function"]["arguments"] == '{"city": "London"}'
        assert result["finish_reason"] == "tool_calls"

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_complete_without_tool_calls(self, mock_acompletion: AsyncMock) -> None:
        """Verify tool_calls key is absent when message.tool_calls is None."""
        # Arrange
        response = _make_completion_response()
        response.choices[0].message.tool_calls = None
        mock_acompletion.return_value = response
        adapter = LiteLLMAdapter()

        # Act
        result = await adapter.complete(_MODEL, _MESSAGES)

        # Assert
        assert "tool_calls" not in result

    @patch("beddel.adapters.litellm_adapter.litellm.acompletion", new_callable=AsyncMock)
    async def test_complete_forwards_tools_kwarg(self, mock_acompletion: AsyncMock) -> None:
        """Verify tools kwarg is forwarded to litellm.acompletion via **kwargs."""
        # Arrange
        mock_acompletion.return_value = _make_completion_response()
        adapter = LiteLLMAdapter()
        tools = [{"type": "function", "function": {"name": "test"}}]

        # Act
        await adapter.complete(_MODEL, _MESSAGES, tools=tools)

        # Assert
        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["tools"] == tools
