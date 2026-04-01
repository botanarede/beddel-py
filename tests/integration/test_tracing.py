"""Integration tests for executor tracing (Story 3.1, Task 6).

Verifies that the :class:`~beddel.domain.executor.WorkflowExecutor` creates
correct OpenTelemetry spans for workflow, step, and primitive execution when
a tracer is injected via the ``tracer=`` constructor parameter.
"""

from __future__ import annotations

from typing import Any

import pytest
from beddel_observability_otel.adapter import OpenTelemetryAdapter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from beddel.adapters.hooks import LifecycleHookManager
from beddel.domain.executor import WorkflowExecutor
from beddel.domain.models import (
    EventType,
    ExecutionContext,
    ExecutionStrategy,
    Step,
    StrategyType,
    Workflow,
)
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_adapter() -> tuple[OpenTelemetryAdapter, InMemorySpanExporter]:
    """Create an OTel adapter wired to an in-memory exporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    adapter = OpenTelemetryAdapter(service_name="beddel-test", tracer_provider=provider)
    return adapter, exporter


class _StepDispatchPrimitive(IPrimitive):
    """Mock primitive returning pre-configured results keyed by step id."""

    def __init__(self, results: dict[str, Any], *, default: Any = None) -> None:
        self._results = results
        self._default = default

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Return the pre-configured result for the current step."""
        return self._results.get(context.current_step_id, self._default)


class _FailingPrimitive(IPrimitive):
    """Mock primitive that always raises RuntimeError."""

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        """Raise an error to exercise the error-span path."""
        msg = "step failed"
        raise RuntimeError(msg)


def _build_executor(
    step_results: dict[str, Any],
    *,
    failing_primitives: set[str] | None = None,
    tracer: OpenTelemetryAdapter | None = None,
) -> WorkflowExecutor:
    """Build a WorkflowExecutor with mock primitives."""
    registry = PrimitiveRegistry()
    registry.register("llm", _StepDispatchPrimitive(step_results))
    if failing_primitives:
        for name in failing_primitives:
            registry.register(name, _FailingPrimitive())
    return WorkflowExecutor(registry, tracer=tracer)


def _simple_workflow(
    *,
    workflow_id: str = "test-wf",
    step_id: str = "step-1",
    primitive: str = "llm",
    model: str = "openai/gpt-4o",
    strategy_type: StrategyType = StrategyType.FAIL,
) -> Workflow:
    """Build a single-step workflow for testing."""
    return Workflow(
        id=workflow_id,
        name="Test Workflow",
        steps=[
            Step(
                id=step_id,
                primitive=primitive,
                config={"model": model, "prompt": "Hello"},
                execution_strategy=ExecutionStrategy(type=strategy_type),
            ),
        ],
    )


def _multi_step_workflow() -> Workflow:
    """Build a two-step workflow for nesting verification."""
    return Workflow(
        id="multi-wf",
        name="Multi-Step Workflow",
        steps=[
            Step(
                id="s1",
                primitive="llm",
                config={"model": "openai/gpt-4o", "prompt": "first"},
            ),
            Step(
                id="s2",
                primitive="llm",
                config={"model": "anthropic/claude-3", "prompt": "second"},
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 6.2 — Full workflow execution with tracing enabled
# ---------------------------------------------------------------------------


class TestWorkflowTracingSpans:
    """Verify workflow, step, and primitive spans are created with correct nesting."""

    @pytest.mark.asyncio
    async def test_single_step_creates_three_span_levels(self) -> None:
        """A single-step workflow produces workflow, step, and primitive spans."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        assert "beddel.primitive.llm" in span_names
        assert "beddel.step.step-1" in span_names
        assert "beddel.workflow" in span_names

    @pytest.mark.asyncio
    async def test_multi_step_creates_spans_for_each_step(self) -> None:
        """A two-step workflow produces spans for both steps and their primitives."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"s1": "r1", "s2": "r2"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _multi_step_workflow()

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        assert span_names.count("beddel.workflow") == 1
        assert "beddel.step.s1" in span_names
        assert "beddel.step.s2" in span_names
        # Two primitive spans (one per step)
        assert span_names.count("beddel.primitive.llm") == 2

    @pytest.mark.asyncio
    async def test_span_finish_order_is_inner_first(self) -> None:
        """Spans finish inner-to-outer: primitive → step → workflow."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        prim_idx = span_names.index("beddel.primitive.llm")
        step_idx = span_names.index("beddel.step.step-1")
        wf_idx = span_names.index("beddel.workflow")

        assert prim_idx < step_idx < wf_idx


# ---------------------------------------------------------------------------
# 6.3 — Token usage attributes on step spans
# ---------------------------------------------------------------------------


class TestTokenUsageAttributes:
    """Verify gen_ai.usage.* attributes are set on step spans when usage data is present."""

    @pytest.mark.asyncio
    async def test_token_usage_set_on_step_span(self) -> None:
        """Step span carries gen_ai.usage.* attributes when result has usage dict."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register(
            "llm",
            _StepDispatchPrimitive(
                {
                    "step-1": {
                        "text": "hello",
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 20,
                            "total_tokens": 30,
                        },
                    },
                }
            ),
        )
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        step_span = next(s for s in spans if s.name == "beddel.step.step-1")
        attrs = dict(step_span.attributes or {})

        assert attrs["gen_ai.usage.input_tokens"] == 10
        assert attrs["gen_ai.usage.output_tokens"] == 20
        assert attrs["gen_ai.usage.total_tokens"] == 30

    @pytest.mark.asyncio
    async def test_no_token_usage_when_result_has_no_usage(self) -> None:
        """Step span omits gen_ai.usage.* attributes when result lacks usage dict."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "plain text"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        step_span = next(s for s in spans if s.name == "beddel.step.step-1")
        attrs = dict(step_span.attributes or {})

        assert "gen_ai.usage.input_tokens" not in attrs
        assert "gen_ai.usage.output_tokens" not in attrs
        assert "gen_ai.usage.total_tokens" not in attrs


# ---------------------------------------------------------------------------
# 6.4 — Custom attributes on spans
# ---------------------------------------------------------------------------


class TestCustomAttributes:
    """Verify beddel.* custom attributes are present on the appropriate spans."""

    @pytest.mark.asyncio
    async def test_workflow_span_has_workflow_id(self) -> None:
        """Workflow span carries beddel.workflow_id attribute."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow(workflow_id="my-wf")

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        wf_span = next(s for s in spans if s.name == "beddel.workflow")
        attrs = dict(wf_span.attributes or {})

        assert attrs["beddel.workflow_id"] == "my-wf"

    @pytest.mark.asyncio
    async def test_step_span_has_step_attributes(self) -> None:
        """Step span carries beddel.step_id, beddel.primitive, beddel.execution_strategy."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        step_span = next(s for s in spans if s.name == "beddel.step.step-1")
        attrs = dict(step_span.attributes or {})

        assert attrs["beddel.step_id"] == "step-1"
        assert attrs["beddel.primitive"] == "llm"
        assert attrs["beddel.execution_strategy"] == "fail"

    @pytest.mark.asyncio
    async def test_primitive_span_has_model_and_provider(self) -> None:
        """Primitive span carries beddel.primitive, beddel.model, beddel.provider."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow(model="openai/gpt-4o")

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        prim_span = next(s for s in spans if s.name == "beddel.primitive.llm")
        attrs = dict(prim_span.attributes or {})

        assert attrs["beddel.primitive"] == "llm"
        assert attrs["beddel.model"] == "openai/gpt-4o"
        assert attrs["beddel.provider"] == "openai"

    @pytest.mark.asyncio
    async def test_primitive_span_without_slash_omits_provider(self) -> None:
        """Primitive span omits beddel.provider when model has no slash."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow(model="gpt-4o")

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        prim_span = next(s for s in spans if s.name == "beddel.primitive.llm")
        attrs = dict(prim_span.attributes or {})

        assert attrs["beddel.model"] == "gpt-4o"
        assert "beddel.provider" not in attrs


# ---------------------------------------------------------------------------
# 6.5 — Tracing disabled (tracer=None)
# ---------------------------------------------------------------------------


class TestTracingDisabled:
    """Verify no spans are created and no overhead when tracer is None."""

    @pytest.mark.asyncio
    async def test_no_spans_when_tracer_is_none(self) -> None:
        """Without patching, tracer is None and no spans are produced."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry)
        workflow = _simple_workflow()

        # Execute WITHOUT patching — tracer stays None
        result = await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        assert len(spans) == 0
        # Workflow still completes successfully
        assert result["step_results"]["step-1"] == "ok"

    @pytest.mark.asyncio
    async def test_no_spans_for_multi_step_when_tracer_is_none(self) -> None:
        """Multi-step workflow produces zero spans when tracer is None."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"s1": "r1", "s2": "r2"}))
        executor = WorkflowExecutor(registry)
        workflow = _multi_step_workflow()

        result = await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        assert len(spans) == 0
        assert result["step_results"]["s1"] == "r1"
        assert result["step_results"]["s2"] == "r2"


# ---------------------------------------------------------------------------
# 6.6 — Error spans
# ---------------------------------------------------------------------------


class TestErrorSpans:
    """Verify error attributes are set on step spans when a step fails."""

    @pytest.mark.asyncio
    async def test_error_attributes_set_on_step_span_with_skip_strategy(self) -> None:
        """Step span carries error=True and error.message when primitive raises (SKIP)."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _FailingPrimitive())
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow(strategy_type=StrategyType.SKIP)

        result = await executor.execute(workflow, inputs={})

        # SKIP strategy returns None for the failed step
        assert result["step_results"]["step-1"] is None

        spans = exporter.get_finished_spans()
        step_span = next(s for s in spans if s.name == "beddel.step.step-1")
        attrs = dict(step_span.attributes or {})

        assert attrs["error"] is True
        assert "step failed" in attrs["error.message"]

    @pytest.mark.asyncio
    async def test_error_span_still_has_step_attributes(self) -> None:
        """Error step span retains beddel.step_id and beddel.primitive attributes."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _FailingPrimitive())
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow(strategy_type=StrategyType.SKIP)

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        step_span = next(s for s in spans if s.name == "beddel.step.step-1")
        attrs = dict(step_span.attributes or {})

        assert attrs["beddel.step_id"] == "step-1"
        assert attrs["beddel.primitive"] == "llm"

    @pytest.mark.asyncio
    async def test_error_with_fail_strategy_raises_and_sets_error_span(self) -> None:
        """FAIL strategy re-raises as ExecutionError; error span is still set."""
        from beddel.domain.errors import ExecutionError

        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _FailingPrimitive())
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow(strategy_type=StrategyType.FAIL)

        with pytest.raises(ExecutionError):
            await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        step_span = next(s for s in spans if s.name == "beddel.step.step-1")
        attrs = dict(step_span.attributes or {})

        assert attrs["error"] is True
        assert "step failed" in attrs["error.message"]


# ---------------------------------------------------------------------------
# 6.7 — Streaming execution with tracing
# ---------------------------------------------------------------------------


class TestStreamingTracing:
    """Verify spans are created for the execute_stream() path."""

    @pytest.mark.asyncio
    async def test_stream_creates_workflow_span(self) -> None:
        """execute_stream() creates a beddel.workflow span."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter, hooks=LifecycleHookManager())
        workflow = _simple_workflow()

        events = []
        async for event in executor.execute_stream(workflow, inputs={}):
            events.append(event)

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        assert "beddel.workflow" in span_names

    @pytest.mark.asyncio
    async def test_stream_creates_step_and_primitive_spans(self) -> None:
        """execute_stream() creates step and primitive spans."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter, hooks=LifecycleHookManager())
        workflow = _simple_workflow()

        async for _ in executor.execute_stream(workflow, inputs={}):
            pass

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        assert "beddel.step.step-1" in span_names
        assert "beddel.primitive.llm" in span_names

    @pytest.mark.asyncio
    async def test_stream_workflow_span_has_workflow_id(self) -> None:
        """execute_stream() workflow span carries beddel.workflow_id attribute."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter, hooks=LifecycleHookManager())
        workflow = _simple_workflow(workflow_id="stream-wf")

        async for _ in executor.execute_stream(workflow, inputs={}):
            pass

        spans = exporter.get_finished_spans()
        wf_span = next(s for s in spans if s.name == "beddel.workflow")
        attrs = dict(wf_span.attributes or {})

        assert attrs["beddel.workflow_id"] == "stream-wf"

    @pytest.mark.asyncio
    async def test_stream_emits_events_alongside_spans(self) -> None:
        """execute_stream() yields lifecycle events while also creating spans."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter, hooks=LifecycleHookManager())
        workflow = _simple_workflow()

        events = []
        async for event in executor.execute_stream(workflow, inputs={}):
            events.append(event)

        # Events are emitted
        event_types = [e.event_type for e in events]
        assert EventType.WORKFLOW_START in event_types
        assert EventType.WORKFLOW_END in event_types

        # Spans are also created
        spans = exporter.get_finished_spans()
        assert len(spans) >= 3  # workflow + step + primitive


class TestTracerDI:
    """Verify tracer injection via WorkflowExecutor constructor (no monkey-patching)."""

    @pytest.mark.asyncio
    async def test_constructor_tracer_produces_spans(self) -> None:
        """WorkflowExecutor(registry, tracer=adapter) produces spans without patching."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter)
        workflow = _simple_workflow()

        await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        assert "beddel.workflow" in span_names
        assert "beddel.step.step-1" in span_names
        assert "beddel.primitive.llm" in span_names

    @pytest.mark.asyncio
    async def test_constructor_tracer_stream_produces_spans(self) -> None:
        """WorkflowExecutor(registry, tracer=adapter) produces spans in streaming mode."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=adapter, hooks=LifecycleHookManager())
        workflow = _simple_workflow()

        async for _ in executor.execute_stream(workflow, inputs={}):
            pass

        spans = exporter.get_finished_spans()
        span_names = [s.name for s in spans]

        assert "beddel.workflow" in span_names
        assert "beddel.step.step-1" in span_names
        assert "beddel.primitive.llm" in span_names

    @pytest.mark.asyncio
    async def test_constructor_tracer_none_produces_no_spans(self) -> None:
        """WorkflowExecutor(registry, tracer=None) produces no spans."""
        adapter, exporter = _make_adapter()
        registry = PrimitiveRegistry()
        registry.register("llm", _StepDispatchPrimitive({"step-1": "ok"}))
        executor = WorkflowExecutor(registry, tracer=None)
        workflow = _simple_workflow()

        result = await executor.execute(workflow, inputs={})

        spans = exporter.get_finished_spans()
        assert len(spans) == 0
        assert result["step_results"]["step-1"] == "ok"
