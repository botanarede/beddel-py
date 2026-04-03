"""Tests for :mod:`beddel.adapters.pii_middleware`."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest

from beddel.adapters.pii_middleware import PIIMiddleware
from beddel.adapters.pii_tokenizer import RegexPIITokenizer
from beddel.domain.models import ExecutionContext


class MockLLMProvider:
    """Mock provider that echoes back messages for testing."""

    def __init__(self, response_content: str = "Response text") -> None:
        self.last_messages: list[dict[str, Any]] = []
        self.response_content = response_content

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.last_messages = messages
        return {"content": self.response_content}

    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        self.last_messages = messages
        for word in self.response_content.split():
            yield word + " "


@pytest.fixture()
def tokenizer() -> RegexPIITokenizer:
    return RegexPIITokenizer()


@pytest.fixture()
def mock_provider() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture()
def context() -> ExecutionContext:
    return ExecutionContext(workflow_id="test-wf")


class TestCompleteTokenizesInput:
    """AC #6 — verify PII is removed from messages sent to provider."""

    @pytest.mark.asyncio()
    async def test_email_tokenized_before_provider(
        self, mock_provider: MockLLMProvider, tokenizer: RegexPIITokenizer
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        messages = [{"role": "user", "content": "Email alice@example.com"}]

        await mw.complete("gpt-4o", messages)

        sent = mock_provider.last_messages[0]["content"]
        assert "alice@example.com" not in sent
        assert "[PII_EMAIL_1]" in sent

    @pytest.mark.asyncio()
    async def test_phone_tokenized_before_provider(
        self, mock_provider: MockLLMProvider, tokenizer: RegexPIITokenizer
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        messages = [{"role": "user", "content": "Call 555-123-4567"}]

        await mw.complete("gpt-4o", messages)

        sent = mock_provider.last_messages[0]["content"]
        assert "555-123-4567" not in sent


class TestCompleteDetokenizesOutput:
    """AC #6 — verify response is de-tokenized if it contains tokens."""

    @pytest.mark.asyncio()
    async def test_response_detokenized(self, tokenizer: RegexPIITokenizer) -> None:
        provider = MockLLMProvider(response_content="Contact [PII_EMAIL_1]")
        mw = PIIMiddleware(provider, tokenizer)
        messages = [{"role": "user", "content": "Email alice@example.com"}]

        result = await mw.complete("gpt-4o", messages)

        assert result["content"] == "Contact alice@example.com"


class TestCompleteNoPiiPassthrough:
    """AC #6 — text without PII passes through unchanged."""

    @pytest.mark.asyncio()
    async def test_no_pii_passthrough(
        self, mock_provider: MockLLMProvider, tokenizer: RegexPIITokenizer
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        messages = [{"role": "user", "content": "Hello world"}]

        result = await mw.complete("gpt-4o", messages)

        assert mock_provider.last_messages[0]["content"] == "Hello world"
        assert result["content"] == "Response text"


class TestStreamTokenizesInput:
    """AC #6 — verify PII removed from messages in stream mode."""

    @pytest.mark.asyncio()
    async def test_stream_tokenizes_messages(
        self, mock_provider: MockLLMProvider, tokenizer: RegexPIITokenizer
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        messages = [{"role": "user", "content": "Email alice@example.com"}]

        chunks = []
        async for chunk in mw.stream("gpt-4o", messages):
            chunks.append(chunk)

        sent = mock_provider.last_messages[0]["content"]
        assert "alice@example.com" not in sent
        assert "[PII_EMAIL_1]" in sent


class TestStreamYieldsChunks:
    """AC #6 — verify chunks are yielded from stream."""

    @pytest.mark.asyncio()
    async def test_stream_yields_all_chunks(
        self, mock_provider: MockLLMProvider, tokenizer: RegexPIITokenizer
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        messages = [{"role": "user", "content": "Hello"}]

        chunks = []
        async for chunk in mw.stream("gpt-4o", messages):
            chunks.append(chunk)

        assert len(chunks) == 2  # "Response " and "text "
        assert "".join(chunks).strip() == "Response text"


class TestMultipleMessages:
    """AC #6 — multiple messages with PII in different ones."""

    @pytest.mark.asyncio()
    async def test_multiple_messages_tokenized(
        self, mock_provider: MockLLMProvider, tokenizer: RegexPIITokenizer
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Email alice@example.com"},
            {"role": "user", "content": "SSN is 123-45-6789"},
        ]

        await mw.complete("gpt-4o", messages)

        sent = mock_provider.last_messages
        assert sent[0]["content"] == "You are helpful."
        assert "alice@example.com" not in sent[1]["content"]
        assert "123-45-6789" not in sent[2]["content"]


class TestMetadataStorage:
    """AC #7 — verify token map stored in context.metadata."""

    @pytest.mark.asyncio()
    async def test_token_map_stored_in_context(
        self,
        mock_provider: MockLLMProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer, context=context)
        messages = [{"role": "user", "content": "Email alice@example.com"}]

        await mw.complete("gpt-4o", messages)

        assert "_pii_token_map" in context.metadata
        tmap = context.metadata["_pii_token_map"]
        assert tmap["[PII_EMAIL_1]"] == "alice@example.com"

    @pytest.mark.asyncio()
    async def test_set_context_stores_map(
        self,
        mock_provider: MockLLMProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        mw.set_context(context)
        messages = [{"role": "user", "content": "SSN is 123-45-6789"}]

        await mw.complete("gpt-4o", messages)

        assert "_pii_token_map" in context.metadata

    @pytest.mark.asyncio()
    async def test_stream_stores_token_map(
        self,
        mock_provider: MockLLMProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer, context=context)
        messages = [{"role": "user", "content": "Email alice@example.com"}]

        async for _ in mw.stream("gpt-4o", messages):
            pass

        assert "_pii_token_map" in context.metadata


class TestNoContextNoError:
    """AC #7 — works without context (just no metadata storage)."""

    @pytest.mark.asyncio()
    async def test_no_context_complete(
        self, mock_provider: MockLLMProvider, tokenizer: RegexPIITokenizer
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        messages = [{"role": "user", "content": "Email alice@example.com"}]

        result = await mw.complete("gpt-4o", messages)

        assert "content" in result

    @pytest.mark.asyncio()
    async def test_no_context_stream(
        self, mock_provider: MockLLMProvider, tokenizer: RegexPIITokenizer
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer)
        messages = [{"role": "user", "content": "Email alice@example.com"}]

        chunks = []
        async for chunk in mw.stream("gpt-4o", messages):
            chunks.append(chunk)

        assert len(chunks) > 0

    @pytest.mark.asyncio()
    async def test_no_pii_no_metadata_stored(
        self,
        mock_provider: MockLLMProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(mock_provider, tokenizer, context=context)
        messages = [{"role": "user", "content": "Hello world"}]

        await mw.complete("gpt-4o", messages)

        assert "_pii_token_map" not in context.metadata
