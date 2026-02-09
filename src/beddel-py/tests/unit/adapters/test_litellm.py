"""Unit tests for the LiteLLM adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from beddel.adapters.litellm import LiteLLMAdapter
from beddel.domain.models import (
    ErrorCode,
    LLMRequest,
    LLMResponse,
    Message,
    ProviderError,
    TokenUsage,
)
from beddel.domain.ports import ILLMProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**overrides: Any) -> LLMRequest:
    """Build a minimal LLMRequest with optional overrides."""
    defaults: dict[str, Any] = {
        "model": "gpt-4o-mini",
        "messages": [Message(role="user", content="Hello")],
    }
    defaults.update(overrides)
    return LLMRequest(**defaults)


def _make_completion_response(
    *,
    content: str = "Hi there!",
    model: str = "gpt-4o-mini",
    finish_reason: str = "stop",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    total_tokens: int = 15,
) -> MagicMock:
    """Build a mock litellm completion response object."""
    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.total_tokens = total_tokens

    response = MagicMock()
    response.choices = [choice]
    response.model = model
    response.usage = usage
    return response


def _make_stream_chunk(content: str | None) -> MagicMock:
    """Build a mock streaming chunk with delta.content."""
    delta = MagicMock()
    delta.content = content

    choice = MagicMock()
    choice.delta = delta

    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


async def _async_iter_chunks(chunks: list[MagicMock]) -> Any:
    """Create an async iterator from a list of mock chunks."""
    for chunk in chunks:
        yield chunk


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter() -> LiteLLMAdapter:
    """LiteLLMAdapter with no credentials."""
    return LiteLLMAdapter()


@pytest.fixture
def llm_request() -> LLMRequest:
    """Minimal LLMRequest fixture."""
    return _make_request()


# ---------------------------------------------------------------------------
# 5.2 complete() happy path
# ---------------------------------------------------------------------------


@patch("beddel.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
async def test_complete_happy_path(
    mock_acompletion: AsyncMock,
    adapter: LiteLLMAdapter,
    llm_request: LLMRequest,
) -> None:
    """complete() maps litellm response to LLMResponse with correct fields."""
    # Arrange
    mock_acompletion.return_value = _make_completion_response(
        content="Hello from LLM!",
        model="gpt-4o-mini",
        finish_reason="stop",
        prompt_tokens=12,
        completion_tokens=8,
        total_tokens=20,
    )

    # Act
    result = await adapter.complete(llm_request)

    # Assert
    assert isinstance(result, LLMResponse)
    assert result.content == "Hello from LLM!"
    assert result.model == "gpt-4o-mini"
    assert result.finish_reason == "stop"
    assert result.usage == TokenUsage(
        prompt_tokens=12, completion_tokens=8, total_tokens=20,
    )
    mock_acompletion.assert_awaited_once()


# ---------------------------------------------------------------------------
# 5.3 complete() with response_format
# ---------------------------------------------------------------------------


@patch("beddel.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
async def test_complete_passes_response_format(
    mock_acompletion: AsyncMock,
    adapter: LiteLLMAdapter,
) -> None:
    """response_format is forwarded to litellm.acompletion()."""
    # Arrange
    fmt = {"type": "json_object"}
    req = _make_request(response_format=fmt)
    mock_acompletion.return_value = _make_completion_response()

    # Act
    await adapter.complete(req)

    # Assert
    call_kwargs = mock_acompletion.call_args[1]
    assert call_kwargs["response_format"] == fmt


# ---------------------------------------------------------------------------
# 5.4 complete() error → ProviderError with BEDDEL-PROVIDER-001
# ---------------------------------------------------------------------------


@patch("beddel.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
async def test_complete_error_raises_provider_error(
    mock_acompletion: AsyncMock,
    adapter: LiteLLMAdapter,
    llm_request: LLMRequest,
) -> None:
    """Exception from litellm.acompletion() is wrapped in ProviderError."""
    # Arrange
    mock_acompletion.side_effect = RuntimeError("API rate limit exceeded")

    # Act & Assert
    with pytest.raises(ProviderError, match="API rate limit exceeded") as exc_info:
        await adapter.complete(llm_request)

    assert exc_info.value.code == ErrorCode.PROVIDER_ERROR
    assert exc_info.value.__cause__ is not None
    assert exc_info.value.details["adapter"] == "litellm"
    assert exc_info.value.details["model"] == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# 5.5 stream() happy path
# ---------------------------------------------------------------------------


@patch("beddel.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
async def test_stream_happy_path(
    mock_acompletion: AsyncMock,
    adapter: LiteLLMAdapter,
    llm_request: LLMRequest,
) -> None:
    """stream() yields content strings from async chunk iterator."""
    # Arrange
    chunks = [
        _make_stream_chunk("Hello"),
        _make_stream_chunk(" "),
        _make_stream_chunk("world"),
    ]
    mock_acompletion.return_value = _async_iter_chunks(chunks)

    # Act
    result: list[str] = []
    async for text in adapter.stream(llm_request):
        result.append(text)

    # Assert
    assert result == ["Hello", " ", "world"]
    call_kwargs = mock_acompletion.call_args[1]
    assert call_kwargs["stream"] is True


# ---------------------------------------------------------------------------
# 5.6 stream() skips None delta content
# ---------------------------------------------------------------------------


@patch("beddel.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
async def test_stream_skips_none_delta_content(
    mock_acompletion: AsyncMock,
    adapter: LiteLLMAdapter,
    llm_request: LLMRequest,
) -> None:
    """stream() skips chunks where delta.content is None."""
    # Arrange
    chunks = [
        _make_stream_chunk("Hello"),
        _make_stream_chunk(None),
        _make_stream_chunk("world"),
        _make_stream_chunk(None),
    ]
    mock_acompletion.return_value = _async_iter_chunks(chunks)

    # Act
    result: list[str] = []
    async for text in adapter.stream(llm_request):
        result.append(text)

    # Assert
    assert result == ["Hello", "world"]


# ---------------------------------------------------------------------------
# 5.7 stream() error → ProviderError
# ---------------------------------------------------------------------------


@patch("beddel.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
async def test_stream_error_raises_provider_error(
    mock_acompletion: AsyncMock,
    adapter: LiteLLMAdapter,
    llm_request: LLMRequest,
) -> None:
    """Exception from litellm.acompletion() during stream is wrapped in ProviderError."""
    # Arrange
    mock_acompletion.side_effect = ConnectionError("Network unreachable")

    # Act & Assert
    with pytest.raises(ProviderError, match="Network unreachable") as exc_info:
        async for _ in adapter.stream(llm_request):
            pass  # pragma: no cover

    assert exc_info.value.code == ErrorCode.PROVIDER_ERROR
    assert exc_info.value.__cause__ is not None
    assert exc_info.value.details["stream"] is True


# ---------------------------------------------------------------------------
# 5.8 api_key and api_base passed through
# ---------------------------------------------------------------------------


@patch("beddel.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
async def test_api_key_and_api_base_passed_through(
    mock_acompletion: AsyncMock,
) -> None:
    """api_key and api_base are forwarded to litellm.acompletion()."""
    # Arrange
    adapter = LiteLLMAdapter(api_key="sk-test-123", api_base="https://api.example.com")
    req = _make_request()
    mock_acompletion.return_value = _make_completion_response()

    # Act
    await adapter.complete(req)

    # Assert
    call_kwargs = mock_acompletion.call_args[1]
    assert call_kwargs["api_key"] == "sk-test-123"
    assert call_kwargs["api_base"] == "https://api.example.com"


# ---------------------------------------------------------------------------
# 5.9 isinstance(LiteLLMAdapter(), ILLMProvider) returns True (AC: 9)
# ---------------------------------------------------------------------------


def test_adapter_satisfies_illm_provider_protocol() -> None:
    """LiteLLMAdapter is a runtime-checkable ILLMProvider."""
    adapter = LiteLLMAdapter()
    assert isinstance(adapter, ILLMProvider)


# ---------------------------------------------------------------------------
# 5.10 Default constructor (no api_key/api_base) works
# ---------------------------------------------------------------------------


@patch("beddel.adapters.litellm.litellm.acompletion", new_callable=AsyncMock)
async def test_default_constructor_no_credentials(
    mock_acompletion: AsyncMock,
) -> None:
    """Adapter with no api_key/api_base omits them from litellm params."""
    # Arrange
    adapter = LiteLLMAdapter()
    req = _make_request()
    mock_acompletion.return_value = _make_completion_response()

    # Act
    await adapter.complete(req)

    # Assert
    call_kwargs = mock_acompletion.call_args[1]
    assert "api_key" not in call_kwargs
    assert "api_base" not in call_kwargs
    assert adapter.api_key is None
    assert adapter.api_base is None
