"""Integration tests for PII tokenization pipeline.

Verifies the full flow: user text with PII → PIIMiddleware → mock provider
(PII never reaches provider) → response → de-tokenized output.

AC #10: tokenization round-trip, pattern matching, middleware transparency,
edge cases (nested PII, overlapping patterns, no PII, empty text).
"""

from __future__ import annotations

import subprocess
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from beddel.adapters.pii_middleware import PIIMiddleware
from beddel.adapters.pii_tokenizer import RegexPIITokenizer
from beddel.domain.models import ExecutionContext

# ---------------------------------------------------------------------------
# Capturing mock provider
# ---------------------------------------------------------------------------


class CapturingProvider:
    """Mock LLM provider that captures messages and echoes them back."""

    def __init__(self) -> None:
        self.captured_messages: list[dict[str, Any]] = []

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.captured_messages = list(messages)
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
        return {"content": f"I received: {user_content}"}

    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        self.captured_messages = list(messages)
        user_content = next((m["content"] for m in messages if m["role"] == "user"), "")
        yield f"I received: {user_content}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def provider() -> CapturingProvider:
    return CapturingProvider()


@pytest.fixture()
def tokenizer() -> RegexPIITokenizer:
    return RegexPIITokenizer()


@pytest.fixture()
def context() -> ExecutionContext:
    return ExecutionContext(workflow_id="pii-integration")


# ---------------------------------------------------------------------------
# Full pipeline — PII never reaches provider (AC #10)
# ---------------------------------------------------------------------------

# Sample PII values used across tests.
_EMAIL = "alice@example.com"
_PHONE = "555-123-4567"
_SSN = "123-45-6789"
_CC = "4111 1111 1111 1111"

_ALL_PII_TEXT = f"Email {_EMAIL}, call {_PHONE}, SSN {_SSN}, card {_CC}"


class TestPiiNeverReachesProvider:
    """Verify that PII is stripped before the provider sees messages."""

    @pytest.mark.asyncio()
    async def test_complete_strips_all_pii(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer, context=context)
        messages = [{"role": "user", "content": _ALL_PII_TEXT}]

        await mw.complete("gpt-4o", messages)

        sent = provider.captured_messages[0]["content"]
        assert _EMAIL not in sent
        assert _PHONE not in sent
        assert _SSN not in sent
        assert _CC not in sent

    @pytest.mark.asyncio()
    async def test_stream_strips_all_pii(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer, context=context)
        messages = [{"role": "user", "content": _ALL_PII_TEXT}]

        async for _ in mw.stream("gpt-4o", messages):
            pass

        sent = provider.captured_messages[0]["content"]
        assert _EMAIL not in sent
        assert _PHONE not in sent
        assert _SSN not in sent
        assert _CC not in sent


# ---------------------------------------------------------------------------
# Round-trip: tokenize → provider echoes tokens → detokenize (AC #10)
# ---------------------------------------------------------------------------


class TestRoundTripPreservesOriginal:
    """Tokenize → provider echoes tokens → detokenize restores original."""

    @pytest.mark.asyncio()
    async def test_complete_round_trip(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer, context=context)
        messages = [{"role": "user", "content": f"Email {_EMAIL}"}]

        result = await mw.complete("gpt-4o", messages)

        # Provider echoes "I received: [PII_EMAIL_1]" → middleware detokenizes.
        assert _EMAIL in result["content"]

    @pytest.mark.asyncio()
    async def test_complete_round_trip_all_types(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer, context=context)
        messages = [{"role": "user", "content": _ALL_PII_TEXT}]

        result = await mw.complete("gpt-4o", messages)

        assert _EMAIL in result["content"]
        assert _PHONE in result["content"]
        assert _SSN in result["content"]
        assert _CC in result["content"]


# ---------------------------------------------------------------------------
# Context metadata populated (AC #7)
# ---------------------------------------------------------------------------


class TestContextMetadataPopulated:
    """Verify token map stored in ExecutionContext.metadata."""

    @pytest.mark.asyncio()
    async def test_metadata_has_token_map(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer, context=context)
        messages = [{"role": "user", "content": f"Email {_EMAIL}"}]

        await mw.complete("gpt-4o", messages)

        assert "_pii_token_map" in context.metadata
        tmap = context.metadata["_pii_token_map"]
        assert tmap["[PII_EMAIL_1]"] == _EMAIL

    @pytest.mark.asyncio()
    async def test_metadata_has_all_pii_types(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer, context=context)
        messages = [{"role": "user", "content": _ALL_PII_TEXT}]

        await mw.complete("gpt-4o", messages)

        tmap = context.metadata["_pii_token_map"]
        assert _EMAIL in tmap.values()
        assert _PHONE in tmap.values()
        assert _SSN in tmap.values()
        assert _CC in tmap.values()


# ---------------------------------------------------------------------------
# Edge cases (AC #10)
# ---------------------------------------------------------------------------


class TestEdgeCaseNoPii:
    """Text without PII passes through unchanged."""

    @pytest.mark.asyncio()
    async def test_no_pii_passthrough(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer)
        messages = [{"role": "user", "content": "Hello world"}]

        result = await mw.complete("gpt-4o", messages)

        assert provider.captured_messages[0]["content"] == "Hello world"
        assert result["content"] == "I received: Hello world"


class TestEdgeCaseEmptyText:
    """Empty text passes through unchanged."""

    @pytest.mark.asyncio()
    async def test_empty_text(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer)
        messages = [{"role": "user", "content": ""}]

        result = await mw.complete("gpt-4o", messages)

        assert provider.captured_messages[0]["content"] == ""
        assert result["content"] == "I received: "


class TestEdgeCaseCreditCardWithSpaces:
    """Credit card with spaces is detected (subtask 5.2)."""

    @pytest.mark.asyncio()
    async def test_cc_spaces_stripped(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer)
        messages = [{"role": "user", "content": f"Card: {_CC}"}]

        await mw.complete("gpt-4o", messages)

        sent = provider.captured_messages[0]["content"]
        assert _CC not in sent
        assert "[PII_CC_1]" in sent


class TestEdgeCaseInternationalPhone:
    """International phone format +1-555-123-4567 is detected (subtask 5.2)."""

    @pytest.mark.asyncio()
    async def test_intl_phone_stripped(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
    ) -> None:
        intl_phone = "+1-555-123-4567"
        mw = PIIMiddleware(provider, tokenizer)
        messages = [{"role": "user", "content": f"Call {intl_phone}"}]

        await mw.complete("gpt-4o", messages)

        sent = provider.captured_messages[0]["content"]
        assert intl_phone not in sent
        assert "[PII_PHONE_1]" in sent


class TestEdgeCaseNestedPii:
    """Email embedded in surrounding text with other PII (subtask 5.2)."""

    @pytest.mark.asyncio()
    async def test_email_and_phone_both_detected(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
    ) -> None:
        text = "Contact alice@example.com or call 555-123-4567 for Alice"
        mw = PIIMiddleware(provider, tokenizer)
        messages = [{"role": "user", "content": text}]

        await mw.complete("gpt-4o", messages)

        sent = provider.captured_messages[0]["content"]
        assert "alice@example.com" not in sent
        assert "555-123-4567" not in sent


class TestEdgeCaseMixedPiiTypes:
    """Text with all 4 PII types detected simultaneously."""

    @pytest.mark.asyncio()
    async def test_all_four_types(
        self,
        provider: CapturingProvider,
        tokenizer: RegexPIITokenizer,
        context: ExecutionContext,
    ) -> None:
        mw = PIIMiddleware(provider, tokenizer, context=context)
        messages = [{"role": "user", "content": _ALL_PII_TEXT}]

        await mw.complete("gpt-4o", messages)

        tmap = context.metadata["_pii_token_map"]
        prefixes = {k.split("_")[1] for k in tmap}
        assert "EMAIL" in prefixes
        assert "PHONE" in prefixes
        assert "SSN" in prefixes
        assert "CC" in prefixes


# ---------------------------------------------------------------------------
# Domain isolation (subtask 5.4)
# ---------------------------------------------------------------------------


class TestDomainIsolation:
    """Verify domain core never imports from adapters."""

    def test_no_adapter_imports_in_domain(self) -> None:
        result = subprocess.run(
            [
                "grep",
                "-r",
                "from beddel.adapters",
                "src/beddel-py/src/beddel/domain/",
            ],
            capture_output=True,
            text=True,
        )
        assert result.stdout == "", f"Domain core imports from adapters:\n{result.stdout}"
