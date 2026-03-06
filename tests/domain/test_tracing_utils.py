"""Unit tests for tracing_utils module."""

from __future__ import annotations

from beddel.domain.tracing_utils import extract_token_usage


class TestExtractTokenUsage:
    """Verify extract_token_usage extracts gen_ai.usage.* attributes correctly."""

    def test_extracts_all_token_fields(self) -> None:
        """Returns gen_ai.usage.* attributes when usage dict is present."""
        result = {
            "text": "hello",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
            },
        }
        attrs = extract_token_usage(result)
        assert attrs == {
            "gen_ai.usage.input_tokens": 10,
            "gen_ai.usage.output_tokens": 20,
            "gen_ai.usage.total_tokens": 30,
        }

    def test_returns_empty_dict_when_no_usage_key(self) -> None:
        """Returns empty dict when result has no usage key."""
        assert extract_token_usage({"text": "hello"}) == {}

    def test_returns_empty_dict_for_non_dict_input(self) -> None:
        """Returns empty dict when input is not a dict."""
        assert extract_token_usage("not a dict") == {}  # type: ignore[arg-type]

    def test_returns_empty_dict_when_usage_is_not_dict(self) -> None:
        """Returns empty dict when usage value is not a dict."""
        assert extract_token_usage({"usage": "not a dict"}) == {}

    def test_defaults_missing_token_fields_to_zero(self) -> None:
        """Missing token fields default to 0."""
        result = {"usage": {}}
        attrs = extract_token_usage(result)
        assert attrs == {
            "gen_ai.usage.input_tokens": 0,
            "gen_ai.usage.output_tokens": 0,
            "gen_ai.usage.total_tokens": 0,
        }

    def test_partial_usage_fields(self) -> None:
        """Only present fields are extracted, missing default to 0."""
        result = {"usage": {"prompt_tokens": 5}}
        attrs = extract_token_usage(result)
        assert attrs["gen_ai.usage.input_tokens"] == 5
        assert attrs["gen_ai.usage.output_tokens"] == 0
        assert attrs["gen_ai.usage.total_tokens"] == 0
