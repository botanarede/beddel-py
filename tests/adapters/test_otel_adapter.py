"""Unit tests for beddel.adapters.otel_adapter module."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from beddel.adapters.otel_adapter import OpenTelemetryAdapter
from beddel.domain.errors import TracingError
from beddel.domain.ports import ITracer
from beddel.error_codes import TRACING_FAILURE

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_adapter() -> tuple[OpenTelemetryAdapter, InMemorySpanExporter]:
    """Create an adapter wired to an in-memory exporter for assertions."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    adapter = OpenTelemetryAdapter(service_name="beddel-test", tracer_provider=provider)
    return adapter, exporter


# ---------------------------------------------------------------------------
# Tests: Interface compliance (AC-2)
# ---------------------------------------------------------------------------


class TestInterfaceCompliance:
    """OpenTelemetryAdapter implements the ITracer port interface."""

    def test_is_subclass_of_itracer(self) -> None:
        assert issubclass(OpenTelemetryAdapter, ITracer)

    def test_instance_is_itracer(self) -> None:
        adapter, _ = _make_adapter()
        assert isinstance(adapter, ITracer)


# ---------------------------------------------------------------------------
# Tests: __init__ (subtask 3.2)
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for OpenTelemetryAdapter constructor."""

    def test_accepts_custom_tracer_provider(self) -> None:
        provider = TracerProvider()
        adapter = OpenTelemetryAdapter(service_name="custom", tracer_provider=provider)
        assert adapter._tracer is not None

    def test_defaults_service_name_to_beddel(self) -> None:
        provider = TracerProvider()
        adapter = OpenTelemetryAdapter(tracer_provider=provider)
        # The tracer should have been created — just verify no error
        assert adapter._tracer is not None

    def test_uses_global_tracer_provider_when_none(self) -> None:
        """When tracer_provider is None, falls back to trace.get_tracer_provider()."""
        adapter = OpenTelemetryAdapter(service_name="default-test")
        # Should create a tracer from the global provider without error
        assert adapter._tracer is not None


# ---------------------------------------------------------------------------
# Tests: start_span (subtask 3.3)
# ---------------------------------------------------------------------------


class TestStartSpan:
    """Tests for OpenTelemetryAdapter.start_span()."""

    def test_creates_span_with_given_name(self) -> None:
        adapter, exporter = _make_adapter()

        span = adapter.start_span("beddel.workflow")
        adapter.end_span(span)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].name == "beddel.workflow"

    def test_sets_attributes_on_span(self) -> None:
        adapter, exporter = _make_adapter()
        attrs = {"beddel.workflow_id": "wf-1", "beddel.model": "gpt-4o"}

        span = adapter.start_span("beddel.workflow", attributes=attrs)
        adapter.end_span(span)

        spans = exporter.get_finished_spans()
        assert spans[0].attributes is not None
        assert spans[0].attributes["beddel.workflow_id"] == "wf-1"
        assert spans[0].attributes["beddel.model"] == "gpt-4o"

    def test_no_attributes_when_none_provided(self) -> None:
        adapter, exporter = _make_adapter()

        span = adapter.start_span("beddel.step.step-1")
        adapter.end_span(span)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        # No custom attributes set — only default OTel attributes
        assert spans[0].attributes is None or len(spans[0].attributes) == 0

    def test_returns_span_object(self) -> None:
        adapter, _ = _make_adapter()

        span = adapter.start_span("test-span")
        assert span is not None
        adapter.end_span(span)


# ---------------------------------------------------------------------------
# Tests: end_span (subtask 3.4)
# ---------------------------------------------------------------------------


class TestEndSpan:
    """Tests for OpenTelemetryAdapter.end_span()."""

    def test_sets_final_attributes_before_ending(self) -> None:
        adapter, exporter = _make_adapter()

        span = adapter.start_span("beddel.step.llm-call")
        adapter.end_span(
            span,
            attributes={
                "gen_ai.usage.input_tokens": 100,
                "gen_ai.usage.output_tokens": 50,
                "gen_ai.usage.total_tokens": 150,
            },
        )

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes is not None
        assert spans[0].attributes["gen_ai.usage.input_tokens"] == 100
        assert spans[0].attributes["gen_ai.usage.output_tokens"] == 50
        assert spans[0].attributes["gen_ai.usage.total_tokens"] == 150

    def test_ends_span_without_attributes(self) -> None:
        adapter, exporter = _make_adapter()

        span = adapter.start_span("beddel.primitive.llm")
        adapter.end_span(span)

        spans = exporter.get_finished_spans()
        assert len(spans) == 1


# ---------------------------------------------------------------------------
# Tests: _extract_token_attributes (subtask 3.5, AC-5)
# ---------------------------------------------------------------------------


class TestExtractTokenAttributes:
    """Tests for OpenTelemetryAdapter._extract_token_attributes()."""

    def test_extracts_usage_from_result(self) -> None:
        result: dict[str, Any] = {
            "content": "Hello!",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

        attrs = OpenTelemetryAdapter._extract_token_attributes(result)

        assert attrs == {
            "gen_ai.usage.input_tokens": 10,
            "gen_ai.usage.output_tokens": 5,
            "gen_ai.usage.total_tokens": 15,
        }

    def test_returns_empty_dict_when_no_usage_key(self) -> None:
        result: dict[str, Any] = {"content": "Hello!"}
        attrs = OpenTelemetryAdapter._extract_token_attributes(result)
        assert attrs == {}

    def test_returns_empty_dict_for_non_dict_input(self) -> None:
        attrs = OpenTelemetryAdapter._extract_token_attributes("not a dict")  # type: ignore[arg-type]
        assert attrs == {}

    def test_returns_empty_dict_when_usage_is_not_dict(self) -> None:
        result: dict[str, Any] = {"usage": "invalid"}
        attrs = OpenTelemetryAdapter._extract_token_attributes(result)
        assert attrs == {}

    def test_defaults_missing_token_fields_to_zero(self) -> None:
        result: dict[str, Any] = {"usage": {"prompt_tokens": 42}}
        attrs = OpenTelemetryAdapter._extract_token_attributes(result)
        assert attrs["gen_ai.usage.input_tokens"] == 42
        assert attrs["gen_ai.usage.output_tokens"] == 0
        assert attrs["gen_ai.usage.total_tokens"] == 0


# ---------------------------------------------------------------------------
# Tests: Span naming for three nesting levels (AC-4)
# ---------------------------------------------------------------------------


class TestSpanNaming:
    """Verify the adapter creates spans with the expected naming patterns."""

    def test_workflow_span_name(self) -> None:
        adapter, exporter = _make_adapter()
        span = adapter.start_span("beddel.workflow")
        adapter.end_span(span)
        assert exporter.get_finished_spans()[0].name == "beddel.workflow"

    def test_step_span_name(self) -> None:
        adapter, exporter = _make_adapter()
        span = adapter.start_span("beddel.step.summarize")
        adapter.end_span(span)
        assert exporter.get_finished_spans()[0].name == "beddel.step.summarize"

    def test_primitive_span_name(self) -> None:
        adapter, exporter = _make_adapter()
        span = adapter.start_span("beddel.primitive.llm")
        adapter.end_span(span)
        assert exporter.get_finished_spans()[0].name == "beddel.primitive.llm"


# ---------------------------------------------------------------------------
# Tests: Custom attributes pass-through (AC-6)
# ---------------------------------------------------------------------------


class TestCustomAttributes:
    """Verify custom beddel.* attributes are set on spans."""

    def test_all_custom_attributes_set(self) -> None:
        adapter, exporter = _make_adapter()
        attrs = {
            "beddel.model": "gpt-4o",
            "beddel.provider": "openai",
            "beddel.execution_strategy": "sequential",
            "beddel.workflow_id": "wf-123",
            "beddel.step_id": "step-1",
            "beddel.primitive": "llm",
        }

        span = adapter.start_span("beddel.step.step-1", attributes=attrs)
        adapter.end_span(span)

        finished = exporter.get_finished_spans()[0]
        assert finished.attributes is not None
        for key, value in attrs.items():
            assert finished.attributes[key] == value


# ---------------------------------------------------------------------------
# Tests: Error resilience
# ---------------------------------------------------------------------------


class TestErrorResilience:
    """Tracing failures should be silently handled."""

    def test_end_span_with_none_span_does_not_raise(self) -> None:
        adapter, _ = _make_adapter()
        # Passing None as span should not crash
        adapter.end_span(None)

    def test_start_span_with_empty_name(self) -> None:
        adapter, exporter = _make_adapter()
        span = adapter.start_span("")
        adapter.end_span(span)
        assert exporter.get_finished_spans()[0].name == ""


# ---------------------------------------------------------------------------
# Tests: TracingError emission (Story 3.6, Task 3 — AC-6)
# ---------------------------------------------------------------------------


class TestTracingErrorEmission:
    """OTel adapter raises TracingError with fail_silent=True on failures."""

    def test_start_span_raises_tracing_error_on_tracer_failure(self) -> None:
        """start_span raises TracingError(fail_silent=True) when tracer fails."""
        adapter, _ = _make_adapter()
        adapter._tracer = MagicMock()
        adapter._tracer.start_span.side_effect = RuntimeError("tracer boom")

        with pytest.raises(TracingError) as exc_info:
            adapter.start_span("beddel.workflow")

        assert exc_info.value.fail_silent is True
        assert exc_info.value.code == TRACING_FAILURE
        assert exc_info.value.__cause__ is not None

    def test_end_span_raises_tracing_error_on_span_end_failure(self) -> None:
        """end_span raises TracingError(fail_silent=True) when span.end() fails."""
        adapter, _ = _make_adapter()
        mock_span = MagicMock()
        mock_span.end.side_effect = RuntimeError("span end boom")

        with pytest.raises(TracingError) as exc_info:
            adapter.end_span(mock_span)

        assert exc_info.value.fail_silent is True
        assert exc_info.value.code == TRACING_FAILURE
        assert exc_info.value.__cause__ is not None

    def test_tracing_error_has_correct_error_code(self) -> None:
        """Raised TracingError carries BEDDEL-ADAPT-010 error code."""
        adapter, _ = _make_adapter()
        adapter._tracer = MagicMock()
        adapter._tracer.start_span.side_effect = RuntimeError("boom")

        with pytest.raises(TracingError) as exc_info:
            adapter.start_span("test-span")

        assert exc_info.value.code == "BEDDEL-ADAPT-010"
