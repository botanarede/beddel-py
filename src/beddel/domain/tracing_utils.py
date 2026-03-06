"""Shared tracing utilities for the Beddel domain core.

Provides helper functions used by both the executor and tracing adapters
to extract span attributes from step results.  No external dependencies
— only stdlib types are used.
"""

from __future__ import annotations

from typing import Any

__all__ = ["extract_token_usage"]


def extract_token_usage(result: dict[str, Any]) -> dict[str, Any]:
    """Extract ``gen_ai.usage.*`` attributes from a step result dict.

    Checks for a ``usage`` key containing a dict with token count fields.
    Returns a dict of ``gen_ai.usage.*`` attributes suitable for passing to
    ``ITracer.end_span``, or an empty dict if no usage data is found.

    Attribute names follow the stable OpenTelemetry ``gen_ai`` semantic
    conventions (``gen_ai.usage.input_tokens``, ``gen_ai.usage.output_tokens``).
    ``gen_ai.usage.total_tokens`` is a custom extension not in the spec but
    useful for cost tracking.

    Args:
        result: A step result dict that may contain a ``usage`` key
            with token count information.

    Returns:
        A dict of ``gen_ai.usage.*`` attributes, or an empty dict.
    """
    if not isinstance(result, dict) or "usage" not in result:
        return {}
    usage = result["usage"]
    if not isinstance(usage, dict):
        return {}
    return {
        "gen_ai.usage.input_tokens": usage.get("prompt_tokens", 0),
        "gen_ai.usage.output_tokens": usage.get("completion_tokens", 0),
        "gen_ai.usage.total_tokens": usage.get("total_tokens", 0),
    }
