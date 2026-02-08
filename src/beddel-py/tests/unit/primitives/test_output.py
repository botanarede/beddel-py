"""Unit tests for the Output-Generator primitive."""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    PrimitiveError,
)
from beddel.primitives.output import output_primitive

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def context() -> ExecutionContext:
    """Minimal ExecutionContext — output primitive does not use it."""
    return ExecutionContext()


# ---------------------------------------------------------------------------
# 3.2 Happy path with dict template
# ---------------------------------------------------------------------------


async def test_dict_template_returned(context: ExecutionContext) -> None:
    """Config with template dict returns the dict as-is."""
    config: dict[str, Any] = {"template": {"topics": "AI", "summary": "Overview"}}

    result = await output_primitive(config, context)

    assert result == {"topics": "AI", "summary": "Overview"}


# ---------------------------------------------------------------------------
# 3.3 Happy path with string template
# ---------------------------------------------------------------------------


async def test_string_template_returned(context: ExecutionContext) -> None:
    """Config with template string returns the string as-is."""
    config: dict[str, Any] = {"template": "Hello, Alice!"}

    result = await output_primitive(config, context)

    assert result == "Hello, Alice!"


# ---------------------------------------------------------------------------
# 3.4 Nested dict template
# ---------------------------------------------------------------------------


async def test_nested_dict_template_returned(context: ExecutionContext) -> None:
    """Deeply nested template dict is returned in full."""
    template = {
        "report": {
            "sections": [{"title": "Intro", "body": "..."}],
            "meta": {"version": 1},
        }
    }
    config: dict[str, Any] = {"template": template}

    result = await output_primitive(config, context)

    assert result == template


# ---------------------------------------------------------------------------
# 3.5 Empty string template
# ---------------------------------------------------------------------------


async def test_empty_string_template(context: ExecutionContext) -> None:
    """Config with template: '' returns empty string."""
    result = await output_primitive({"template": ""}, context)

    assert result == ""


# ---------------------------------------------------------------------------
# 3.6 Empty dict template
# ---------------------------------------------------------------------------


async def test_empty_dict_template(context: ExecutionContext) -> None:
    """Config with template: {} returns empty dict."""
    result = await output_primitive({"template": {}}, context)

    assert result == {}


# ---------------------------------------------------------------------------
# 3.7 Missing template key raises PrimitiveError
# ---------------------------------------------------------------------------


async def test_missing_template_raises_primitive_error(context: ExecutionContext) -> None:
    """Missing 'template' key raises PrimitiveError with BEDDEL-EXEC-001."""
    with pytest.raises(PrimitiveError, match="template") as exc_info:
        await output_primitive({"model": "x"}, context)

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.8 Extra config keys are ignored
# ---------------------------------------------------------------------------


async def test_extra_config_keys_ignored(context: ExecutionContext) -> None:
    """Extra keys beyond 'template' do not affect the result."""
    config: dict[str, Any] = {"template": "output", "extra": 42, "other": [1, 2]}

    result = await output_primitive(config, context)

    assert result == "output"


# ---------------------------------------------------------------------------
# 3.9 Context accepted but not used
# ---------------------------------------------------------------------------


async def test_context_accepted_but_unused() -> None:
    """Primitive accepts context with arbitrary metadata without using it."""
    ctx = ExecutionContext(
        workflow_id="wf-123",
        input={"name": "test"},
        step_results={"prev": "data"},
        metadata={"llm_provider": "should-be-ignored"},
    )

    result = await output_primitive({"template": "ok"}, ctx)

    assert result == "ok"
