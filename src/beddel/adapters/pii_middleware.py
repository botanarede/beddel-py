"""PII middleware that wraps an ILLMProvider with transparent tokenization."""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from typing import Any

from beddel.domain.models import ExecutionContext, TokenMap
from beddel.domain.ports import ILLMProvider, IPIITokenizer

# Matches PII token placeholders like [PII_EMAIL_1].
_TOKEN_RE = re.compile(r"\[PII_[A-Z]+_\d+\]")


class PIIMiddleware:
    """Transparent PII tokenization middleware for LLM providers.

    Wraps an :class:`ILLMProvider` and tokenizes message content before
    forwarding to the provider, then de-tokenizes the response.

    Implements :class:`ILLMProvider` so it can be used as a drop-in
    replacement anywhere a provider is expected.
    """

    def __init__(
        self,
        provider: ILLMProvider,
        tokenizer: IPIITokenizer,
        context: ExecutionContext | None = None,
    ) -> None:
        self._provider = provider
        self._tokenizer = tokenizer
        self._context = context

    def set_context(self, context: ExecutionContext) -> None:
        """Set the execution context for token map storage."""
        self._context = context

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Tokenize messages, call provider, de-tokenize response."""
        tokenized_messages, combined_map = self._tokenize_messages(messages)
        self._store_token_map(combined_map)

        result = await self._provider.complete(model, tokenized_messages, **kwargs)

        if "content" in result and combined_map and _TOKEN_RE.search(result["content"]):
            result["content"] = self._tokenizer.detokenize(result["content"], combined_map)

        return result

    async def stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """Tokenize messages, stream from provider, yield chunks as-is.

        Stream chunks are yielded without de-tokenization since tokens
        appear in the input (not output). The token map is stored in
        context metadata for the caller to de-tokenize the assembled
        response if needed.
        """
        tokenized_messages, combined_map = self._tokenize_messages(messages)
        self._store_token_map(combined_map)

        async for chunk in self._provider.stream(model, tokenized_messages, **kwargs):
            yield chunk

    def _tokenize_messages(
        self, messages: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], TokenMap]:
        """Tokenize content fields in all messages."""
        combined_map: TokenMap = {}
        tokenized: list[dict[str, Any]] = []

        for msg in messages:
            new_msg = dict(msg)
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                tok_content, tmap = self._tokenizer.tokenize(content)
                new_msg["content"] = tok_content
                combined_map.update(tmap)
            tokenized.append(new_msg)

        return tokenized, combined_map

    def _store_token_map(self, token_map: TokenMap) -> None:
        """Store token map in execution context metadata if available."""
        if self._context is not None and token_map:
            self._context.metadata["_pii_token_map"] = token_map
