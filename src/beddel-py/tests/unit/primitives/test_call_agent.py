"""Unit tests for the Call-Agent primitive."""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.models import (
    ErrorCode,
    ExecutionContext,
    ParseError,
    PrimitiveError,
    StepDefinition,
    WorkflowConfig,
    WorkflowDefinition,
    WorkflowMetadata,
)
from beddel.domain.registry import PrimitiveRegistry
from beddel.primitives.call_agent import call_agent_primitive

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_workflow(
    steps: list[StepDefinition] | None = None,
) -> WorkflowDefinition:
    """Build a minimal WorkflowDefinition for testing."""
    return WorkflowDefinition(
        metadata=WorkflowMetadata(name="child-wf", version="1.0.0"),
        workflow=steps or [],
        config=WorkflowConfig(),
    )


def _make_context(
    registry: PrimitiveRegistry | None = None,
    workflow_loader: Any = None,
    call_depth: int = 0,
    extra_metadata: dict[str, Any] | None = None,
) -> ExecutionContext:
    """Build an ExecutionContext with call-agent metadata."""
    meta: dict[str, Any] = {}
    if registry is not None:
        meta["registry"] = registry
    if workflow_loader is not None:
        meta["workflow_loader"] = workflow_loader
    meta["call_depth"] = call_depth
    if extra_metadata:
        meta.update(extra_metadata)
    return ExecutionContext(metadata=meta)


# ---------------------------------------------------------------------------
# 3.2 Happy path: valid config returns nested workflow output
# ---------------------------------------------------------------------------


async def test_happy_path_returns_nested_output() -> None:
    """Valid agentId + loader + registry → returns nested workflow output."""
    # Register a simple echo primitive
    registry = PrimitiveRegistry()

    async def echo_primitive(config: dict[str, Any], context: ExecutionContext) -> Any:
        return config.get("value", "echoed")

    registry.register_func("echo", echo_primitive)

    step = StepDefinition(id="s1", type="echo", config={"value": "hello"}, result="out")
    workflow = _make_workflow(steps=[step])
    loader = lambda agent_id: workflow  # noqa: E731

    ctx = _make_context(registry=registry, workflow_loader=loader)
    config: dict[str, Any] = {"agentId": "child-agent", "input": {"key": "val"}}

    result = await call_agent_primitive(config, ctx)

    # The last step has result="out", so output = step_results dict
    assert result is not None


# ---------------------------------------------------------------------------
# 3.3 Missing agentId raises PrimitiveError
# ---------------------------------------------------------------------------


async def test_missing_agent_id_raises() -> None:
    """Missing 'agentId' raises PrimitiveError with BEDDEL-EXEC-001."""
    ctx = _make_context(registry=PrimitiveRegistry(), workflow_loader=lambda x: None)

    with pytest.raises(PrimitiveError, match="agentId") as exc_info:
        await call_agent_primitive({"input": {}}, ctx)

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.4 Missing workflow_loader raises PrimitiveError
# ---------------------------------------------------------------------------


async def test_missing_workflow_loader_raises() -> None:
    """Missing 'workflow_loader' in metadata raises PrimitiveError."""
    ctx = ExecutionContext(metadata={"registry": PrimitiveRegistry(), "call_depth": 0})

    with pytest.raises(PrimitiveError, match="workflow_loader") as exc_info:
        await call_agent_primitive({"agentId": "x"}, ctx)

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.5 Default input {} when not provided
# ---------------------------------------------------------------------------


async def test_default_input_empty_dict() -> None:
    """When config has no 'input', default {} is used."""
    registry = PrimitiveRegistry()

    captured_input: dict[str, Any] = {}

    async def capture_primitive(config: dict[str, Any], context: ExecutionContext) -> Any:
        captured_input.update(context.input)
        return "done"

    registry.register_func("capture", capture_primitive)

    step = StepDefinition(id="s1", type="capture", config={})
    workflow = _make_workflow(steps=[step])
    loader = lambda agent_id: workflow  # noqa: E731

    ctx = _make_context(registry=registry, workflow_loader=loader)

    await call_agent_primitive({"agentId": "child"}, ctx)

    assert captured_input == {}


# ---------------------------------------------------------------------------
# 3.6 Max depth exceeded raises PrimitiveError
# ---------------------------------------------------------------------------


async def test_max_depth_exceeded_raises() -> None:
    """Exceeding max_depth raises PrimitiveError with BEDDEL-EXEC-001."""
    ctx = _make_context(
        registry=PrimitiveRegistry(),
        workflow_loader=lambda x: None,
        call_depth=5,
    )

    with pytest.raises(PrimitiveError, match="max recursion depth") as exc_info:
        await call_agent_primitive({"agentId": "x", "max_depth": 5}, ctx)

    assert exc_info.value.code == ErrorCode.EXEC_STEP_FAILED


# ---------------------------------------------------------------------------
# 3.7 ParseError from workflow_loader propagates
# ---------------------------------------------------------------------------


async def test_parse_error_propagates() -> None:
    """ParseError from workflow_loader propagates as-is."""

    def bad_loader(agent_id: str) -> None:
        raise ParseError(
            "bad yaml",
            code=ErrorCode.PARSE_INVALID_YAML,
            details={"file": "test.yaml"},
        )

    ctx = _make_context(registry=PrimitiveRegistry(), workflow_loader=bad_loader)

    with pytest.raises(ParseError, match="bad yaml"):
        await call_agent_primitive({"agentId": "broken"}, ctx)


# ---------------------------------------------------------------------------
# 3.8 Nested workflow failure wraps error in PrimitiveError
# ---------------------------------------------------------------------------


async def test_nested_failure_wraps_error() -> None:
    """When nested workflow step fails, error is wrapped in PrimitiveError."""
    registry = PrimitiveRegistry()

    async def failing_primitive(config: dict[str, Any], context: ExecutionContext) -> Any:
        raise ValueError("boom")

    registry.register_func("fail", failing_primitive)

    step = StepDefinition(id="s1", type="fail", config={})
    workflow = _make_workflow(steps=[step])
    loader = lambda agent_id: workflow  # noqa: E731

    ctx = _make_context(registry=registry, workflow_loader=loader)

    with pytest.raises(PrimitiveError, match="failed"):
        await call_agent_primitive({"agentId": "bad-child"}, ctx)


# ---------------------------------------------------------------------------
# 3.9 Custom max_depth from config is respected
# ---------------------------------------------------------------------------


async def test_custom_max_depth_respected() -> None:
    """Config max_depth=2 is respected over default 5."""
    ctx = _make_context(
        registry=PrimitiveRegistry(),
        workflow_loader=lambda x: None,
        call_depth=2,
    )

    with pytest.raises(PrimitiveError, match="2/2"):
        await call_agent_primitive({"agentId": "x", "max_depth": 2}, ctx)


async def test_custom_max_depth_allows_execution() -> None:
    """Config max_depth=10 allows deeper nesting."""
    registry = PrimitiveRegistry()

    async def noop(config: dict[str, Any], context: ExecutionContext) -> Any:
        return "ok"

    registry.register_func("noop", noop)

    step = StepDefinition(id="s1", type="noop", config={})
    workflow = _make_workflow(steps=[step])
    loader = lambda agent_id: workflow  # noqa: E731

    ctx = _make_context(registry=registry, workflow_loader=loader, call_depth=7)

    # max_depth=10, current=7 → allowed
    result = await call_agent_primitive({"agentId": "deep", "max_depth": 10}, ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# 3.10 call_depth is incremented in child context
# ---------------------------------------------------------------------------


async def test_call_depth_incremented_in_child() -> None:
    """Child context has call_depth incremented by 1."""
    registry = PrimitiveRegistry()
    observed_depth: list[int] = []

    async def depth_checker(config: dict[str, Any], context: ExecutionContext) -> Any:
        observed_depth.append(context.metadata.get("call_depth", -1))
        return "checked"

    registry.register_func("check-depth", depth_checker)

    step = StepDefinition(id="s1", type="check-depth", config={})
    workflow = _make_workflow(steps=[step])
    loader = lambda agent_id: workflow  # noqa: E731

    ctx = _make_context(registry=registry, workflow_loader=loader, call_depth=2)

    await call_agent_primitive({"agentId": "child"}, ctx)

    assert observed_depth == [3]  # 2 + 1


# ---------------------------------------------------------------------------
# A1: Async workflow loader support
# ---------------------------------------------------------------------------


async def test_async_workflow_loader_supported() -> None:
    """Async workflow_loader is awaited correctly."""
    registry = PrimitiveRegistry()

    async def noop(config: dict[str, Any], context: ExecutionContext) -> Any:
        return "async-ok"

    registry.register_func("noop", noop)

    step = StepDefinition(id="s1", type="noop", config={})
    workflow = _make_workflow(steps=[step])

    async def async_loader(agent_id: str) -> WorkflowDefinition:
        return workflow

    ctx = _make_context(registry=registry, workflow_loader=async_loader)
    result = await call_agent_primitive({"agentId": "async-child"}, ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# A5: Metadata passthrough to child context
# ---------------------------------------------------------------------------


async def test_metadata_passes_through_to_child() -> None:
    """Extra metadata keys from parent context propagate to child."""
    registry = PrimitiveRegistry()
    observed_meta: dict[str, Any] = {}

    async def meta_checker(config: dict[str, Any], context: ExecutionContext) -> Any:
        observed_meta.update(context.metadata)
        return "checked"

    registry.register_func("check-meta", meta_checker)

    step = StepDefinition(id="s1", type="check-meta", config={})
    workflow = _make_workflow(steps=[step])
    loader = lambda agent_id: workflow  # noqa: E731

    ctx = _make_context(
        registry=registry,
        workflow_loader=loader,
        extra_metadata={"custom_key": "custom_value", "another": 42},
    )

    await call_agent_primitive({"agentId": "child"}, ctx)

    assert observed_meta["custom_key"] == "custom_value"
    assert observed_meta["another"] == 42
    assert observed_meta["call_depth"] == 1
