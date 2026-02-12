"""Unit tests for beddel.domain.registry module."""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.errors import PrimitiveError
from beddel.domain.models import ExecutionContext
from beddel.domain.ports import IPrimitive
from beddel.domain.registry import PrimitiveRegistry, default_registry, primitive


class DummyPrimitive(IPrimitive):
    """Concrete IPrimitive for testing — returns config as-is."""

    async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
        return config


class TestRegisterAndGet:
    """Tests for PrimitiveRegistry.register() and .get()."""

    def test_register_and_retrieve_by_name(self) -> None:
        registry = PrimitiveRegistry()
        prim = DummyPrimitive()

        registry.register("my-prim", prim)

        assert registry.get("my-prim") is prim

    def test_register_overwrites_existing(self) -> None:
        registry = PrimitiveRegistry()
        first = DummyPrimitive()
        second = DummyPrimitive()

        registry.register("prim", first)
        registry.register("prim", second)

        assert registry.get("prim") is second


class TestGetUnknown:
    """Tests for PrimitiveRegistry.get() with unknown names."""

    def test_raises_primitive_error_for_unknown_name(self) -> None:
        registry = PrimitiveRegistry()

        with pytest.raises(PrimitiveError) as exc_info:
            registry.get("nonexistent")

        assert exc_info.value.code == "BEDDEL-PRIM-001"

    def test_error_message_contains_name(self) -> None:
        registry = PrimitiveRegistry()

        with pytest.raises(PrimitiveError) as exc_info:
            registry.get("ghost")

        assert "ghost" in exc_info.value.message

    def test_error_details_contain_name(self) -> None:
        registry = PrimitiveRegistry()

        with pytest.raises(PrimitiveError) as exc_info:
            registry.get("missing")

        assert exc_info.value.details == {"name": "missing"}


class TestRegisterInvalidPrimitive:
    """Tests for PrimitiveRegistry.register() with non-IPrimitive objects."""

    def test_raises_primitive_error_for_plain_object(self) -> None:
        registry = PrimitiveRegistry()

        with pytest.raises(PrimitiveError) as exc_info:
            registry.register("bad", object())  # type: ignore[arg-type]

        assert exc_info.value.code == "BEDDEL-PRIM-002"

    def test_error_message_contains_type_name(self) -> None:
        registry = PrimitiveRegistry()

        with pytest.raises(PrimitiveError) as exc_info:
            registry.register("bad", "not-a-primitive")  # type: ignore[arg-type]

        assert "str" in exc_info.value.message

    def test_error_details_contain_name_and_type(self) -> None:
        registry = PrimitiveRegistry()

        with pytest.raises(PrimitiveError) as exc_info:
            registry.register("bad", 42)  # type: ignore[arg-type]

        assert exc_info.value.details == {"name": "bad", "type": "int"}


class TestHas:
    """Tests for PrimitiveRegistry.has()."""

    def test_returns_true_for_registered(self) -> None:
        registry = PrimitiveRegistry()
        registry.register("present", DummyPrimitive())

        assert registry.has("present") is True

    def test_returns_false_for_unregistered(self) -> None:
        registry = PrimitiveRegistry()

        assert registry.has("absent") is False


class TestListPrimitives:
    """Tests for PrimitiveRegistry.list_primitives()."""

    def test_empty_registry_returns_empty_list(self) -> None:
        registry = PrimitiveRegistry()

        assert registry.list_primitives() == []

    def test_returns_all_registered_names_sorted(self) -> None:
        registry = PrimitiveRegistry()
        registry.register("zebra", DummyPrimitive())
        registry.register("alpha", DummyPrimitive())
        registry.register("middle", DummyPrimitive())

        assert registry.list_primitives() == ["alpha", "middle", "zebra"]


class TestPrimitiveDecorator:
    """Tests for the @primitive decorator."""

    def test_decorator_registers_class_in_default_registry(self) -> None:
        @primitive("test-decorator-prim")
        class _TestPrim(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return config

        assert default_registry.has("test-decorator-prim")
        assert isinstance(default_registry.get("test-decorator-prim"), IPrimitive)

    def test_decorator_returns_original_class(self) -> None:
        @primitive("test-decorator-returns")
        class _ReturnPrim(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return config

        assert isinstance(_ReturnPrim(), IPrimitive)

    def test_decorator_raises_for_non_iprimitive_class(self) -> None:
        with pytest.raises(PrimitiveError) as exc_info:

            @primitive("bad-decorator")
            class _NotAPrimitive:  # type: ignore[type-var]
                pass

        assert exc_info.value.code == "BEDDEL-PRIM-002"
        assert "_NotAPrimitive" in exc_info.value.message

    def test_custom_primitive_registration_via_decorator(self) -> None:
        """AC-2: custom primitives can be registered via @primitive."""

        @primitive("custom-user-prim")
        class CustomUserPrimitive(IPrimitive):
            async def execute(self, config: dict[str, Any], context: ExecutionContext) -> Any:
                return {"custom": True, **config}

        assert default_registry.has("custom-user-prim")
        retrieved = default_registry.get("custom-user-prim")
        assert isinstance(retrieved, CustomUserPrimitive)
