"""Unit tests for the OpenTelemetryAdapter."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from beddel.adapters.tracing import OpenTelemetryAdapter
from beddel.domain.models import StepDefinition, WorkflowDefinition, WorkflowMetadata
from beddel.domain.ports import ITracer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step() -> StepDefinition:
    """Build a minimal StepDefinition for testing."""
    return StepDefinition(id="step-1", type="llm")


def _make_workflow() -> WorkflowDefinition:
    """Build a minimal WorkflowDefinition for testing."""
    return WorkflowDefinition(
        metadata=WorkflowMetadata(name="test-agent", version="2.0.0"),
        workflow=[],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_tracer_provider() -> None:
    """Allow TracerProvider to be set once per test by resetting the guard."""
    trace._TRACER_PROVIDER_SET_ONCE._done = False  # noqa: SLF001


@pytest.fixture
def otel_exporter(_reset_tracer_provider: None) -> InMemorySpanExporter:
    """TracerProvider with InMemorySpanExporter for test span capture."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter  # type: ignore[misc]
    exporter.shutdown()


@pytest.fixture
def adapter(otel_exporter: InMemorySpanExporter) -> OpenTelemetryAdapter:
    """Fresh adapter using the test TracerProvider."""
    return OpenTelemetryAdapter()


# ---------------------------------------------------------------------------
# 6.2 start_workflow_span creates span with correct name and attributes (AC: 2)
# ---------------------------------------------------------------------------


def test_start_workflow_span_creates_span_with_correct_name_and_attributes(
    adapter: OpenTelemetryAdapter,
    otel_exporter: InMemorySpanExporter,
) -> None:
    """start_workflow_span creates a span named beddel.workflow.<name> with metadata attributes."""
    # Arrange
    workflow = _make_workflow()

    # Act
    span = adapter.start_workflow_span(workflow)
    adapter.end_span(span)

    # Assert
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    wf_span = spans[0]
    assert wf_span.name == "beddel.workflow.test-agent"
    assert wf_span.attributes is not None
    assert wf_span.attributes["beddel.workflow.name"] == "test-agent"
    assert wf_span.attributes["beddel.workflow.version"] == "2.0.0"
    assert "beddel.workflow.id" in wf_span.attributes
    assert isinstance(wf_span.attributes["beddel.workflow.id"], str)
    assert len(wf_span.attributes["beddel.workflow.id"]) == 32  # 128-bit trace ID as hex


# ---------------------------------------------------------------------------
# 6.3 start_step_span creates child span with correct name and attributes (AC: 3)
# ---------------------------------------------------------------------------


def test_start_step_span_creates_child_span_with_correct_name_and_attributes(
    adapter: OpenTelemetryAdapter,
    otel_exporter: InMemorySpanExporter,
) -> None:
    """start_step_span creates a child span named beddel.step.<id> linked to parent."""
    # Arrange
    workflow = _make_workflow()
    step = _make_step()

    # Act
    parent_span = adapter.start_workflow_span(workflow)
    child_span = adapter.start_step_span(step, parent_span)
    adapter.end_span(child_span)
    adapter.end_span(parent_span)

    # Assert
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 2

    # Spans are finished in order: child first, then parent
    step_span = spans[0]
    wf_span = spans[1]

    assert step_span.name == "beddel.step.step-1"
    assert step_span.attributes is not None
    assert step_span.attributes["beddel.step.id"] == "step-1"
    assert step_span.attributes["beddel.step.type"] == "llm"

    # Child span's parent context matches the workflow span
    assert step_span.parent is not None
    assert step_span.parent.span_id == wf_span.context.span_id


# ---------------------------------------------------------------------------
# 6.4 end_span without error sets status OK (AC: 4)
# ---------------------------------------------------------------------------


def test_end_span_without_error_sets_status_ok(
    adapter: OpenTelemetryAdapter,
    otel_exporter: InMemorySpanExporter,
) -> None:
    """end_span() without error sets span status to OK."""
    # Arrange
    workflow = _make_workflow()
    span = adapter.start_workflow_span(workflow)

    # Act
    adapter.end_span(span)

    # Assert
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].status.status_code == StatusCode.OK


# ---------------------------------------------------------------------------
# 6.5 end_span with error records event and sets status ERROR (AC: 4)
# ---------------------------------------------------------------------------


def test_end_span_with_error_records_event_and_sets_status_error(
    adapter: OpenTelemetryAdapter,
    otel_exporter: InMemorySpanExporter,
) -> None:
    """end_span() with error sets ERROR status, description, and error event."""
    # Arrange
    workflow = _make_workflow()
    span = adapter.start_workflow_span(workflow)

    # Act
    adapter.end_span(span, error="something failed")

    # Assert
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 1
    finished = spans[0]

    assert finished.status.status_code == StatusCode.ERROR
    assert finished.status.description == "something failed"

    # Error event recorded
    assert len(finished.events) == 1
    event = finished.events[0]
    assert event.name == "error"
    assert event.attributes is not None
    assert event.attributes["error.message"] == "something failed"


# ---------------------------------------------------------------------------
# 6.6 isinstance(OpenTelemetryAdapter(), ITracer) returns True (AC: 6)
# ---------------------------------------------------------------------------


def test_adapter_satisfies_itracer_protocol(
    otel_exporter: InMemorySpanExporter,
) -> None:
    """OpenTelemetryAdapter is a runtime-checkable ITracer."""
    adapter = OpenTelemetryAdapter()
    assert isinstance(adapter, ITracer)


# ---------------------------------------------------------------------------
# 6.7 Tracing failure caught and logged as warning, does not propagate (AC: 9)
# ---------------------------------------------------------------------------


def test_tracing_failure_caught_and_logged(
    otel_exporter: InMemorySpanExporter,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tracing failures are caught, logged as WARNING, and never propagate."""
    # Arrange
    adapter = OpenTelemetryAdapter()
    workflow = _make_workflow()
    step = _make_step()

    # --- start_workflow_span failure ---
    with (
        patch.object(adapter, "_tracer") as mock_tracer,
        caplog.at_level(logging.WARNING, logger="beddel.adapters.tracing"),
    ):
        mock_tracer.start_span.side_effect = RuntimeError("tracer exploded")

        # Act — should NOT raise
        result = adapter.start_workflow_span(workflow)

        # Assert
        assert result is trace.INVALID_SPAN
        assert any("Failed to start workflow span" in r.message for r in caplog.records)
        assert all(r.levelno == logging.WARNING for r in caplog.records)

    caplog.clear()

    # --- start_step_span failure ---
    with (
        patch.object(adapter, "_tracer") as mock_tracer,
        caplog.at_level(logging.WARNING, logger="beddel.adapters.tracing"),
    ):
        mock_tracer.start_span.side_effect = RuntimeError("tracer exploded")

        # Act — should NOT raise
        result = adapter.start_step_span(step, MagicMock())

        # Assert
        assert result is trace.INVALID_SPAN
        assert any("Failed to start step span" in r.message for r in caplog.records)

    caplog.clear()

    # --- end_span failure ---
    broken_span = MagicMock()
    broken_span.set_status.side_effect = RuntimeError("span broken")

    with caplog.at_level(logging.WARNING, logger="beddel.adapters.tracing"):
        # Act — should NOT raise
        adapter.end_span(broken_span)

        # Assert
        assert any("Failed to end span" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# 6.8 Span attribute values match expected beddel.* namespace (AC: 10)
# ---------------------------------------------------------------------------


def test_span_attributes_use_beddel_namespace(
    adapter: OpenTelemetryAdapter,
    otel_exporter: InMemorySpanExporter,
) -> None:
    """All span attribute keys use the beddel.* namespace."""
    # Arrange
    workflow = _make_workflow()
    step = _make_step()

    # Act
    parent_span = adapter.start_workflow_span(workflow)
    child_span = adapter.start_step_span(step, parent_span)
    adapter.end_span(child_span)
    adapter.end_span(parent_span)

    # Assert
    spans = otel_exporter.get_finished_spans()
    assert len(spans) == 2

    for span in spans:
        assert span.attributes is not None
        for key in span.attributes:
            assert str(key).startswith("beddel."), (
                f"Attribute key {key!r} does not use beddel.* namespace"
            )
