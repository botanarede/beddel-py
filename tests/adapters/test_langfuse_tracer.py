"""Tests for :class:`~beddel.adapters.langfuse_tracer.LangfuseTracerAdapter`."""

from __future__ import annotations

import logging
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from beddel.adapters.langfuse_tracer import LangfuseTracerAdapter
from beddel.domain.ports import ITracer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The adapter does ``from langfuse import Langfuse`` inside __init__.
# Since ``langfuse`` may not be installed, we inject a fake module into
# ``sys.modules`` and patch the class on it.


def _make_adapter(**kwargs: Any) -> tuple[LangfuseTracerAdapter, MagicMock]:
    """Build an adapter with a mocked Langfuse client.

    Returns ``(adapter, mock_client_instance)``.
    """
    fake_langfuse_mod = MagicMock()
    client_instance = MagicMock()
    fake_langfuse_mod.Langfuse.return_value = client_instance

    with patch.dict(sys.modules, {"langfuse": fake_langfuse_mod}):
        adapter = LangfuseTracerAdapter(
            public_key=kwargs.pop("public_key", "pk-test"),
            secret_key=kwargs.pop("secret_key", "sk-test"),
            **kwargs,
        )
    return adapter, client_instance


def _make_failing_adapter() -> LangfuseTracerAdapter:
    """Build an adapter whose Langfuse init raises (graceful degradation)."""
    fake_mod = MagicMock()
    fake_mod.Langfuse.side_effect = RuntimeError("boom")
    with patch.dict(sys.modules, {"langfuse": fake_mod}):
        return LangfuseTracerAdapter(public_key="pk", secret_key="sk")


# ===================================================================
# ABC conformance
# ===================================================================


class TestABCConformance:
    """Verify ``LangfuseTracerAdapter`` satisfies the ``ITracer`` port."""

    def test_is_subclass_of_itracer(self) -> None:
        assert issubclass(LangfuseTracerAdapter, ITracer)


# ===================================================================
# Constructor
# ===================================================================


class TestConstructor:
    """Verify constructor wiring and defaults."""

    def test_client_stored_on_success(self) -> None:
        adapter, client = _make_adapter()
        assert adapter._client is client

    def test_langfuse_client_initialized_with_keys(self) -> None:
        fake_mod = MagicMock()
        with patch.dict(sys.modules, {"langfuse": fake_mod}):
            LangfuseTracerAdapter(
                public_key="pk-abc",
                secret_key="sk-xyz",
                host="https://custom.host",
            )
            fake_mod.Langfuse.assert_called_once_with(
                public_key="pk-abc",
                secret_key="sk-xyz",
                host="https://custom.host",
            )

    def test_default_host_is_localhost(self) -> None:
        fake_mod = MagicMock()
        with patch.dict(sys.modules, {"langfuse": fake_mod}):
            LangfuseTracerAdapter(public_key="pk", secret_key="sk")
            call_kwargs = fake_mod.Langfuse.call_args[1]
            assert call_kwargs["host"] == "http://localhost:3000"

    def test_enabled_false_skips_client_init(self) -> None:
        fake_mod = MagicMock()
        with patch.dict(sys.modules, {"langfuse": fake_mod}):
            adapter = LangfuseTracerAdapter(public_key="pk", secret_key="sk", enabled=False)
            fake_mod.Langfuse.assert_not_called()
            assert adapter._client is None


# ===================================================================
# Constructor — graceful degradation
# ===================================================================


class TestConstructorGracefulDegradation:
    """If Langfuse init raises, adapter degrades to no-op."""

    def test_client_is_none_on_init_failure(self) -> None:
        adapter = _make_failing_adapter()
        assert adapter._client is None

    def test_no_exception_propagated(self) -> None:
        # Should NOT raise.
        _make_failing_adapter()


# ===================================================================
# start_span — happy path
# ===================================================================


class TestStartSpan:
    """Happy-path span creation."""

    def test_trace_called_with_name(self) -> None:
        adapter, client = _make_adapter()
        adapter.start_span("beddel.workflow")
        client.trace.assert_called_once()
        call_kwargs = client.trace.call_args[1]
        assert call_kwargs["name"] == "beddel.workflow"

    def test_generic_attributes_stored_as_metadata(self) -> None:
        adapter, client = _make_adapter()
        adapter.start_span("s", attributes={"foo": "bar", "baz": 42})
        call_kwargs = client.trace.call_args[1]
        assert call_kwargs["metadata"] == {"foo": "bar", "baz": 42}

    def test_returns_span_handle(self) -> None:
        adapter, client = _make_adapter()
        span = adapter.start_span("s")
        assert span is client.trace.return_value

    def test_prompt_name_stored_in_metadata(self) -> None:
        adapter, client = _make_adapter()
        adapter.start_span("s", attributes={"prompt_name": "my-prompt"})
        call_kwargs = client.trace.call_args[1]
        assert call_kwargs["metadata"]["prompt_name"] == "my-prompt"

    def test_model_stored_in_metadata(self) -> None:
        adapter, client = _make_adapter()
        adapter.start_span("s", attributes={"model": "gpt-4"})
        call_kwargs = client.trace.call_args[1]
        assert call_kwargs["metadata"]["model"] == "gpt-4"

    def test_usage_mapped_to_langfuse_format(self) -> None:
        adapter, client = _make_adapter()
        usage = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        adapter.start_span("s", attributes={"usage": usage})
        call_kwargs = client.trace.call_args[1]
        assert call_kwargs["usage"] == {"input": 100, "output": 50, "total": 150}

    def test_no_metadata_key_when_no_attributes(self) -> None:
        adapter, client = _make_adapter()
        adapter.start_span("s")
        call_kwargs = client.trace.call_args[1]
        assert "metadata" not in call_kwargs


# ===================================================================
# start_span — graceful degradation
# ===================================================================


class TestStartSpanGracefulDegradation:
    """If trace() raises, return None without propagating."""

    def test_returns_none_on_trace_failure(self) -> None:
        adapter, client = _make_adapter()
        client.trace.side_effect = RuntimeError("network error")
        result = adapter.start_span("s")
        assert result is None

    def test_no_exception_propagated(self) -> None:
        adapter, client = _make_adapter()
        client.trace.side_effect = RuntimeError("network error")
        # Should NOT raise.
        adapter.start_span("s")


class TestStartSpanDisabled:
    """When client is None (disabled / failed init), start_span is no-op."""

    def test_returns_none_when_client_is_none(self) -> None:
        adapter = _make_failing_adapter()
        assert adapter.start_span("s") is None

    def test_returns_none_when_enabled_false(self) -> None:
        adapter = LangfuseTracerAdapter(public_key="pk", secret_key="sk", enabled=False)
        assert adapter.start_span("s") is None


# ===================================================================
# end_span — happy path
# ===================================================================


class TestEndSpan:
    """Happy-path span completion and cost tracking."""

    def test_calls_end_on_span(self) -> None:
        span = MagicMock()
        adapter, _ = _make_adapter()
        adapter.end_span(span)
        span.end.assert_called_once()

    def test_usage_attributes_mapped_for_cost_tracking(self) -> None:
        span = MagicMock()
        adapter, _ = _make_adapter()
        usage = {
            "prompt_tokens": 200,
            "completion_tokens": 80,
            "total_tokens": 280,
        }
        adapter.end_span(span, attributes={"usage": usage})
        span.update.assert_called_once()
        update_kwargs = span.update.call_args[1]
        assert update_kwargs["usage"] == {"input": 200, "output": 80, "total": 280}

    def test_generic_attributes_stored_as_metadata(self) -> None:
        span = MagicMock()
        adapter, _ = _make_adapter()
        adapter.end_span(span, attributes={"latency_ms": 42})
        update_kwargs = span.update.call_args[1]
        assert update_kwargs["metadata"] == {"latency_ms": 42}

    def test_none_span_is_noop(self) -> None:
        adapter, _ = _make_adapter()
        # Should NOT raise.
        adapter.end_span(None)

    def test_none_span_with_attributes_is_noop(self) -> None:
        adapter, _ = _make_adapter()
        adapter.end_span(None, attributes={"foo": "bar"})

    def test_no_update_when_no_attributes(self) -> None:
        span = MagicMock()
        adapter, _ = _make_adapter()
        adapter.end_span(span)
        span.update.assert_not_called()


# ===================================================================
# end_span — graceful degradation
# ===================================================================


class TestEndSpanGracefulDegradation:
    """If span.end() raises, log warning and swallow."""

    def test_warning_logged_on_end_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        span = MagicMock()
        span.end.side_effect = RuntimeError("oops")
        adapter, _ = _make_adapter()
        with caplog.at_level(logging.WARNING):
            adapter.end_span(span)
        assert any("Failed to end Langfuse span" in r.message for r in caplog.records)

    def test_no_exception_propagated(self) -> None:
        span = MagicMock()
        span.end.side_effect = RuntimeError("oops")
        adapter, _ = _make_adapter()
        # Should NOT raise.
        adapter.end_span(span)


# ===================================================================
# flush
# ===================================================================


class TestFlush:
    """Verify flush delegates to client."""

    def test_flush_calls_client_flush(self) -> None:
        adapter, client = _make_adapter()
        adapter.flush()
        client.flush.assert_called_once()

    def test_flush_noop_when_disabled(self) -> None:
        adapter = LangfuseTracerAdapter(public_key="pk", secret_key="sk", enabled=False)
        # Should NOT raise (no client to call).
        adapter.flush()


# ===================================================================
# shutdown
# ===================================================================


class TestShutdown:
    """Verify shutdown flushes then shuts down client."""

    def test_shutdown_calls_flush_then_shutdown(self) -> None:
        adapter, client = _make_adapter()
        adapter.shutdown()
        client.flush.assert_called_once()
        client.shutdown.assert_called_once()

    def test_shutdown_noop_when_disabled(self) -> None:
        adapter = LangfuseTracerAdapter(public_key="pk", secret_key="sk", enabled=False)
        # Should NOT raise.
        adapter.shutdown()


# ===================================================================
# flush — graceful degradation
# ===================================================================


class TestFlushGracefulDegradation:
    """If client.flush() raises, log warning and swallow."""

    def test_warning_logged_on_flush_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        adapter, client = _make_adapter()
        client.flush.side_effect = RuntimeError("flush failed")
        with caplog.at_level(logging.WARNING):
            adapter.flush()
        assert any("Failed to flush Langfuse" in r.message for r in caplog.records)

    def test_no_exception_propagated(self) -> None:
        adapter, client = _make_adapter()
        client.flush.side_effect = RuntimeError("flush failed")
        # Should NOT raise.
        adapter.flush()
