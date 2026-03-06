"""Unit tests for ITracer and NoOpTracer port interfaces."""

from __future__ import annotations

import pytest

from beddel.domain.ports import ITracer, NoOpTracer


class TestITracer:
    """Tests for the ITracer abstract base class."""

    def test_cannot_instantiate_directly(self) -> None:
        """ITracer is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            ITracer()  # type: ignore[abstract]

    def test_defines_start_span_method(self) -> None:
        """ITracer defines start_span as an abstract method."""
        assert hasattr(ITracer, "start_span")
        assert getattr(ITracer.start_span, "__isabstractmethod__", False)

    def test_defines_end_span_method(self) -> None:
        """ITracer defines end_span as an abstract method."""
        assert hasattr(ITracer, "end_span")
        assert getattr(ITracer.end_span, "__isabstractmethod__", False)


class TestNoOpTracer:
    """Tests for the NoOpTracer no-op implementation."""

    def test_start_span_returns_none(self) -> None:
        """start_span returns None (no span created)."""
        tracer = NoOpTracer()
        result = tracer.start_span("test.span")
        assert result is None

    def test_start_span_with_attributes_returns_none(self) -> None:
        """start_span with attributes still returns None."""
        tracer = NoOpTracer()
        result = tracer.start_span("test.span", {"key": "value"})
        assert result is None

    def test_end_span_accepts_none(self) -> None:
        """end_span accepts None as span (from NoOpTracer.start_span)."""
        tracer = NoOpTracer()
        tracer.end_span(None)  # Should not raise

    def test_end_span_with_attributes(self) -> None:
        """end_span with attributes does not raise."""
        tracer = NoOpTracer()
        tracer.end_span(None, {"key": "value"})  # Should not raise

    def test_end_span_accepts_any_span(self) -> None:
        """end_span accepts any object as span."""
        tracer = NoOpTracer()
        tracer.end_span("fake-span")  # Should not raise
        tracer.end_span(42)  # Should not raise

    def test_implements_itracer(self) -> None:
        """NoOpTracer is a valid ITracer implementation."""
        tracer = NoOpTracer()
        assert isinstance(tracer, ITracer)


class TestPublicExports:
    """Tests for public API exports."""

    def test_itracer_importable_from_beddel(self) -> None:
        """ITracer is importable from the top-level beddel package."""
        from beddel import ITracer as PublicITracer

        assert PublicITracer is ITracer

    def test_nooptracer_importable_from_beddel(self) -> None:
        """NoOpTracer is importable from the top-level beddel package."""
        from beddel import NoOpTracer as PublicNoOpTracer

        assert PublicNoOpTracer is NoOpTracer
