"""Unit tests for port interfaces (ITracer, NoOpTracer, ILifecycleHook, IHookManager)."""

from __future__ import annotations

import asyncio

import pytest

from beddel.domain.ports import ILifecycleHook, ITracer, NoOpTracer


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


class TestILifecycleHookOnDecision:
    """Tests for the on_decision method on ILifecycleHook."""

    def test_has_on_decision_method(self) -> None:
        """ILifecycleHook defines an on_decision method."""
        assert hasattr(ILifecycleHook, "on_decision")

    def test_on_decision_is_async(self) -> None:
        """on_decision is a coroutine function."""
        hook = ILifecycleHook()
        result = hook.on_decision("use-cache", ["skip-cache", "invalidate"], "faster")
        assert asyncio.iscoroutine(result)
        # Clean up the coroutine to avoid RuntimeWarning
        result.close()

    async def test_on_decision_noop_does_not_raise(self) -> None:
        """Default on_decision is a no-op and does not raise."""
        hook = ILifecycleHook()
        await hook.on_decision("use-cache", ["skip-cache", "invalidate"], "faster")

    async def test_on_decision_returns_none(self) -> None:
        """Default on_decision returns None."""
        hook = ILifecycleHook()
        result = await hook.on_decision("use-cache", [], "no alternatives")
        assert result is None

    async def test_on_decision_accepts_empty_alternatives(self) -> None:
        """on_decision accepts an empty alternatives list."""
        hook = ILifecycleHook()
        await hook.on_decision("proceed", [], "only option")


class TestIHookManager:
    """Tests for the IHookManager class."""

    def test_ihookmanager_exists(self) -> None:
        """IHookManager is importable from ports."""
        from beddel.domain.ports import IHookManager

        assert IHookManager is not None

    def test_ihookmanager_extends_ilifecyclehook(self) -> None:
        """IHookManager is a subclass of ILifecycleHook."""
        from beddel.domain.ports import IHookManager

        assert issubclass(IHookManager, ILifecycleHook)

    def test_ihookmanager_instantiable(self) -> None:
        """IHookManager can be instantiated (plain class, not abstract)."""
        from beddel.domain.ports import IHookManager

        manager = IHookManager()
        assert isinstance(manager, IHookManager)
        assert isinstance(manager, ILifecycleHook)

    def test_has_add_hook_method(self) -> None:
        """IHookManager defines an add_hook method."""
        from beddel.domain.ports import IHookManager

        assert hasattr(IHookManager, "add_hook")

    def test_has_remove_hook_method(self) -> None:
        """IHookManager defines a remove_hook method."""
        from beddel.domain.ports import IHookManager

        assert hasattr(IHookManager, "remove_hook")

    async def test_add_hook_is_noop(self) -> None:
        """Default add_hook is a no-op and does not raise."""
        from beddel.domain.ports import IHookManager

        manager = IHookManager()
        hook = ILifecycleHook()
        await manager.add_hook(hook)

    async def test_remove_hook_is_noop(self) -> None:
        """Default remove_hook is a no-op and does not raise."""
        from beddel.domain.ports import IHookManager

        manager = IHookManager()
        hook = ILifecycleHook()
        await manager.remove_hook(hook)

    async def test_add_hook_returns_none(self) -> None:
        """Default add_hook returns None."""
        from beddel.domain.ports import IHookManager

        manager = IHookManager()
        result = await manager.add_hook(ILifecycleHook())
        assert result is None

    async def test_remove_hook_returns_none(self) -> None:
        """Default remove_hook returns None."""
        from beddel.domain.ports import IHookManager

        manager = IHookManager()
        result = await manager.remove_hook(ILifecycleHook())
        assert result is None

    def test_inherits_lifecycle_methods(self) -> None:
        """IHookManager inherits all ILifecycleHook methods."""
        from beddel.domain.ports import IHookManager

        manager = IHookManager()
        assert hasattr(manager, "on_workflow_start")
        assert hasattr(manager, "on_workflow_end")
        assert hasattr(manager, "on_step_start")
        assert hasattr(manager, "on_step_end")
        assert hasattr(manager, "on_error")
        assert hasattr(manager, "on_retry")
        assert hasattr(manager, "on_decision")

    def test_in_ports_all(self) -> None:
        """IHookManager is in ports.py __all__."""
        from beddel.domain import ports

        assert "IHookManager" in ports.__all__


class TestIHookManagerExports:
    """Tests for IHookManager and IContextReducer exports from domain."""

    def test_ihookmanager_importable_from_domain(self) -> None:
        """IHookManager is importable from beddel.domain."""
        from beddel.domain import IHookManager
        from beddel.domain.ports import IHookManager as PortsIHookManager

        assert IHookManager is PortsIHookManager

    def test_icontext_reducer_importable_from_domain(self) -> None:
        """IContextReducer is importable from beddel.domain."""
        from beddel.domain import IContextReducer
        from beddel.domain.ports import IContextReducer as PortsIContextReducer

        assert IContextReducer is PortsIContextReducer

    def test_ihookmanager_in_domain_all(self) -> None:
        """IHookManager is in domain __all__."""
        from beddel import domain

        assert "IHookManager" in domain.__all__

    def test_icontext_reducer_in_domain_all(self) -> None:
        """IContextReducer is in domain __all__."""
        from beddel import domain

        assert "IContextReducer" in domain.__all__


class TestICircuitBreaker:
    """Tests for the ICircuitBreaker Protocol interface."""

    def test_has_record_failure_method(self) -> None:
        """ICircuitBreaker defines a record_failure method."""
        from beddel.domain.ports import ICircuitBreaker

        assert hasattr(ICircuitBreaker, "record_failure")

    def test_has_record_success_method(self) -> None:
        """ICircuitBreaker defines a record_success method."""
        from beddel.domain.ports import ICircuitBreaker

        assert hasattr(ICircuitBreaker, "record_success")

    def test_has_is_open_method(self) -> None:
        """ICircuitBreaker defines an is_open method."""
        from beddel.domain.ports import ICircuitBreaker

        assert hasattr(ICircuitBreaker, "is_open")

    def test_has_state_method(self) -> None:
        """ICircuitBreaker defines a state method."""
        from beddel.domain.ports import ICircuitBreaker

        assert hasattr(ICircuitBreaker, "state")

    def test_in_ports_all(self) -> None:
        """ICircuitBreaker is in ports.py __all__."""
        from beddel.domain import ports

        assert "ICircuitBreaker" in ports.__all__

    def test_importable_from_domain(self) -> None:
        """ICircuitBreaker is importable from beddel.domain."""
        from beddel.domain import ICircuitBreaker
        from beddel.domain.ports import ICircuitBreaker as PortsICircuitBreaker

        assert ICircuitBreaker is PortsICircuitBreaker

    def test_in_domain_all(self) -> None:
        """ICircuitBreaker is in domain __all__."""
        from beddel import domain

        assert "ICircuitBreaker" in domain.__all__

    def test_execution_dependencies_has_circuit_breaker(self) -> None:
        """ExecutionDependencies Protocol defines circuit_breaker property."""
        from beddel.domain.ports import ExecutionDependencies

        hints = ExecutionDependencies.__protocol_attrs__
        assert "circuit_breaker" in hints
