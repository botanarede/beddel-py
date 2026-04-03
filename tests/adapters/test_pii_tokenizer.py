"""Tests for :mod:`beddel.adapters.pii_tokenizer`."""

from __future__ import annotations

import pytest

from beddel.adapters.pii_tokenizer import DEFAULT_PII_PATTERNS, RegexPIITokenizer
from beddel.domain.errors import PIIError
from beddel.domain.models import PIIPattern
from beddel.error_codes import (
    PII_DETOKENIZATION_FAILED,
    PII_TOKEN_MAP_CORRUPTED,
    PII_TOKENIZATION_FAILED,
)


class TestTokenizeEmail:
    """AC #4 — email pattern detection."""

    def test_single_email(self) -> None:
        tok = RegexPIITokenizer()
        text = "Contact me at alice@example.com please."
        result, tmap = tok.tokenize(text)
        assert "alice@example.com" not in result
        assert "[PII_EMAIL_1]" in result
        assert tmap["[PII_EMAIL_1]"] == "alice@example.com"

    def test_multiple_emails(self) -> None:
        tok = RegexPIITokenizer()
        text = "Send to alice@example.com and bob@test.org"
        result, tmap = tok.tokenize(text)
        assert len(tmap) == 2
        assert "alice@example.com" not in result
        assert "bob@test.org" not in result


class TestTokenizePhone:
    """AC #4 — phone pattern detection (US formats)."""

    def test_us_phone_plain(self) -> None:
        tok = RegexPIITokenizer()
        text = "Call 555-123-4567 now."
        result, tmap = tok.tokenize(text)
        assert "555-123-4567" not in result
        assert len(tmap) == 1

    def test_us_phone_with_country_code(self) -> None:
        tok = RegexPIITokenizer()
        text = "Call +1-555-123-4567 now."
        result, tmap = tok.tokenize(text)
        assert "555-123-4567" not in result
        assert len(tmap) == 1

    def test_us_phone_parens(self) -> None:
        tok = RegexPIITokenizer()
        text = "Call (555) 123-4567 now."
        result, tmap = tok.tokenize(text)
        assert "(555) 123-4567" not in result
        assert len(tmap) == 1


class TestTokenizeSSN:
    """AC #4 — SSN pattern detection."""

    def test_ssn(self) -> None:
        tok = RegexPIITokenizer()
        text = "SSN is 123-45-6789."
        result, tmap = tok.tokenize(text)
        assert "123-45-6789" not in result
        assert "[PII_SSN_1]" in result
        assert tmap["[PII_SSN_1]"] == "123-45-6789"


class TestTokenizeCreditCard:
    """AC #4 — credit card pattern detection."""

    def test_card_with_spaces(self) -> None:
        tok = RegexPIITokenizer()
        text = "Card: 4111 1111 1111 1111"
        result, tmap = tok.tokenize(text)
        assert "4111 1111 1111 1111" not in result
        assert len(tmap) == 1

    def test_card_with_dashes(self) -> None:
        tok = RegexPIITokenizer()
        text = "Card: 4111-1111-1111-1111"
        result, tmap = tok.tokenize(text)
        assert "4111-1111-1111-1111" not in result
        assert len(tmap) == 1

    def test_card_no_separators(self) -> None:
        tok = RegexPIITokenizer()
        text = "Card: 4111111111111111"
        result, tmap = tok.tokenize(text)
        assert "4111111111111111" not in result
        assert len(tmap) == 1


class TestTokenizeMultipleTypes:
    """AC #4 — text with mixed PII types."""

    def test_email_phone_ssn(self) -> None:
        tok = RegexPIITokenizer()
        text = "Email alice@example.com, call 555-123-4567, SSN 123-45-6789"
        result, tmap = tok.tokenize(text)
        assert len(tmap) == 3
        assert "alice@example.com" not in result
        assert "555-123-4567" not in result
        assert "123-45-6789" not in result


class TestRoundTrip:
    """AC #5 — tokenize then detokenize returns original text."""

    def test_round_trip_email(self) -> None:
        tok = RegexPIITokenizer()
        original = "Contact alice@example.com for details."
        tokenized, tmap = tok.tokenize(original)
        restored = tok.detokenize(tokenized, tmap)
        assert restored == original

    def test_round_trip_all_types(self) -> None:
        tok = RegexPIITokenizer()
        original = (
            "Email alice@example.com, call 555-123-4567, SSN 123-45-6789, card 4111 1111 1111 1111"
        )
        tokenized, tmap = tok.tokenize(original)
        restored = tok.detokenize(tokenized, tmap)
        assert restored == original


class TestEdgeCases:
    """AC #5 — edge cases: empty text, no PII, overlapping patterns."""

    def test_empty_text(self) -> None:
        tok = RegexPIITokenizer()
        result, tmap = tok.tokenize("")
        assert result == ""
        assert tmap == {}

    def test_no_pii(self) -> None:
        tok = RegexPIITokenizer()
        text = "Hello world, nothing sensitive here."
        result, tmap = tok.tokenize(text)
        assert result == text
        assert tmap == {}

    def test_overlapping_patterns(self) -> None:
        """SSN pattern (123-45-6789) could partially overlap with phone.

        Patterns are applied in order; once a region is claimed, later
        patterns skip it.
        """
        tok = RegexPIITokenizer()
        text = "SSN 123-45-6789"
        result, tmap = tok.tokenize(text)
        # SSN pattern comes before phone in DEFAULT_PII_PATTERNS,
        # so it should claim the match.
        assert "[PII_SSN_1]" in result
        assert len(tmap) == 1


class TestCustomPatterns:
    """AC #4 — overridable via constructor."""

    def test_custom_pattern(self) -> None:
        custom = [
            PIIPattern(
                name="custom_id",
                pattern=r"ID-\d{6}",
                replacement_prefix="CUSTOM",
            ),
        ]
        tok = RegexPIITokenizer(patterns=custom)
        text = "Your ID-123456 is confirmed."
        result, tmap = tok.tokenize(text)
        assert "ID-123456" not in result
        assert "[PII_CUSTOM_1]" in result
        assert tmap["[PII_CUSTOM_1]"] == "ID-123456"

    def test_custom_patterns_ignore_default(self) -> None:
        """Custom patterns replace defaults entirely."""
        custom = [
            PIIPattern(name="noop", pattern=r"ZZZZZ", replacement_prefix="NOOP"),
        ]
        tok = RegexPIITokenizer(patterns=custom)
        text = "Email alice@example.com"
        result, tmap = tok.tokenize(text)
        # Default email pattern not applied.
        assert "alice@example.com" in result
        assert tmap == {}


class TestTokenizationError:
    """AC #5 — invalid regex raises PIIError."""

    def test_invalid_regex(self) -> None:
        bad = [PIIPattern(name="bad", pattern=r"[invalid", replacement_prefix="BAD")]
        tok = RegexPIITokenizer(patterns=bad)
        with pytest.raises(PIIError) as exc_info:
            tok.tokenize("some text")
        assert exc_info.value.code == PII_TOKENIZATION_FAILED


class TestDetokenizationErrors:
    """AC #5 — detokenization error cases."""

    def test_missing_token_in_map(self) -> None:
        """Empty token map short-circuits — returns text unchanged."""
        tok = RegexPIITokenizer()
        result = tok.detokenize("Hello [PII_EMAIL_1]", {})
        assert result == "Hello [PII_EMAIL_1]"

    def test_missing_token_with_nonempty_map(self) -> None:
        tok = RegexPIITokenizer()
        with pytest.raises(PIIError) as exc_info:
            tok.detokenize(
                "Hello [PII_EMAIL_1] and [PII_PHONE_2]",
                {"[PII_EMAIL_1]": "alice@example.com"},
                # [PII_PHONE_2] missing from map
            )
        assert exc_info.value.code == PII_DETOKENIZATION_FAILED

    def test_token_map_corrupted(self) -> None:
        """Map has entries but text has no tokens."""
        tok = RegexPIITokenizer()
        with pytest.raises(PIIError) as exc_info:
            tok.detokenize(
                "Hello world, no tokens here.",
                {"[PII_EMAIL_1]": "alice@example.com"},
            )
        assert exc_info.value.code == PII_TOKEN_MAP_CORRUPTED

    def test_empty_map_returns_text(self) -> None:
        tok = RegexPIITokenizer()
        result = tok.detokenize("Hello world", {})
        assert result == "Hello world"


class TestDefaultPatternsExist:
    """Verify DEFAULT_PII_PATTERNS is a non-empty list of PIIPattern."""

    def test_default_patterns_populated(self) -> None:
        assert len(DEFAULT_PII_PATTERNS) >= 4
        for p in DEFAULT_PII_PATTERNS:
            assert isinstance(p, PIIPattern)
            assert p.name
            assert p.pattern
            assert p.replacement_prefix
