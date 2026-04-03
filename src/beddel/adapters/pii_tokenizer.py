"""Regex-based PII tokenizer adapter.

Implements :class:`~beddel.domain.ports.IPIITokenizer` using configurable
regex patterns to detect and replace PII before LLM calls.
"""

from __future__ import annotations

import re

from beddel.domain.errors import PIIError
from beddel.domain.models import PIIPattern, TokenMap
from beddel.error_codes import (
    PII_DETOKENIZATION_FAILED,
    PII_TOKEN_MAP_CORRUPTED,
    PII_TOKENIZATION_FAILED,
)

DEFAULT_PII_PATTERNS: list[PIIPattern] = [
    PIIPattern(
        name="email",
        pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        replacement_prefix="EMAIL",
    ),
    PIIPattern(
        name="ssn",
        pattern=r"\b\d{3}-\d{2}-\d{4}\b",
        replacement_prefix="SSN",
    ),
    PIIPattern(
        name="credit_card",
        pattern=r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        replacement_prefix="CC",
    ),
    PIIPattern(
        name="phone",
        pattern=r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        replacement_prefix="PHONE",
    ),
]


# Token placeholder regex used during detokenization.
_TOKEN_RE = re.compile(r"\[PII_[A-Z]+_\d+\]")


class RegexPIITokenizer:
    """Regex-based PII tokenizer implementing :class:`~beddel.domain.ports.IPIITokenizer`.

    Scans text for PII using configurable regex patterns and replaces
    matches with deterministic tokens of the form ``[PII_{PREFIX}_{N}]``.
    The counter *N* resets on each :meth:`tokenize` call.

    Args:
        patterns: Optional list of :class:`PIIPattern` definitions.
            Defaults to :data:`DEFAULT_PII_PATTERNS`.
    """

    def __init__(self, patterns: list[PIIPattern] | None = None) -> None:
        self._patterns = patterns if patterns is not None else DEFAULT_PII_PATTERNS

    def tokenize(self, text: str) -> tuple[str, TokenMap]:
        """Replace PII in *text* with tokens.

        Patterns are applied in list order.  Already-tokenized regions are
        skipped to prevent double-tokenization of overlapping matches.

        Returns:
            ``(tokenized_text, token_map)`` — the token map maps each
            placeholder (e.g. ``[PII_EMAIL_1]``) to the original value.

        Raises:
            PIIError: If a compiled regex raises :class:`re.error`.
        """
        if not text:
            return ("", {})

        token_map: TokenMap = {}
        counter = 0
        # Track tokenized byte-regions to avoid double-tokenization.
        tokenized_regions: list[tuple[int, int]] = []
        # Collect (start, end, replacement, original) then apply right-to-left.
        replacements: list[tuple[int, int, str, str]] = []

        for pii_pattern in self._patterns:
            try:
                compiled = re.compile(pii_pattern.pattern)
            except re.error as exc:
                raise PIIError(
                    PII_TOKENIZATION_FAILED,
                    f"Invalid regex for pattern '{pii_pattern.name}': {exc}",
                    {"pattern_name": pii_pattern.name},
                ) from exc

            try:
                matches = list(compiled.finditer(text))
            except re.error as exc:  # pragma: no cover — defensive
                raise PIIError(
                    PII_TOKENIZATION_FAILED,
                    f"Regex matching failed for pattern '{pii_pattern.name}': {exc}",
                    {"pattern_name": pii_pattern.name},
                ) from exc

            for m in matches:
                start, end = m.start(), m.end()
                if self._overlaps(start, end, tokenized_regions):
                    continue
                counter += 1
                token = f"[PII_{pii_pattern.replacement_prefix}_{counter}]"
                replacements.append((start, end, token, m.group()))
                tokenized_regions.append((start, end))

        # Sort by start position descending so right-to-left replacement
        # preserves earlier indices.
        replacements.sort(key=lambda r: r[0], reverse=True)

        result = text
        for start, end, token, original in replacements:
            token_map[token] = original
            result = result[:start] + token + result[end:]

        return (result, token_map)

    def detokenize(self, text: str, token_map: TokenMap) -> str:
        """Restore original PII values from tokens.

        Raises:
            PIIError: If a token in *text* is not found in *token_map*,
                or if *token_map* has entries but *text* contains no tokens.
        """
        if not token_map:
            return text

        # Check for corrupted state: map has entries but text has no tokens.
        tokens_in_text = _TOKEN_RE.findall(text)
        if not tokens_in_text:
            raise PIIError(
                PII_TOKEN_MAP_CORRUPTED,
                "Token map has entries but text contains no PII tokens.",
                {"token_map_size": len(token_map)},
            )

        result = text
        for token in tokens_in_text:
            if token not in token_map:
                raise PIIError(
                    PII_DETOKENIZATION_FAILED,
                    f"Token {token!r} not found in token map.",
                    {"missing_token": token},
                )
            result = result.replace(token, token_map[token])

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _overlaps(
        start: int,
        end: int,
        regions: list[tuple[int, int]],
    ) -> bool:
        """Return ``True`` if [start, end) overlaps any existing region."""
        return any(start < r_end and end > r_start for r_start, r_end in regions)
