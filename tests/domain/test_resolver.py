"""Unit tests for beddel.domain.resolver module."""

from __future__ import annotations

from typing import Any

import pytest

from beddel.domain.errors import ResolveError
from beddel.domain.models import ExecutionContext
from beddel.domain.resolver import VariableResolver


def _ctx(
    inputs: dict[str, Any] | None = None,
    step_results: dict[str, Any] | None = None,
) -> ExecutionContext:
    """Build a minimal ExecutionContext for testing."""
    return ExecutionContext(
        workflow_id="test-wf",
        inputs=inputs or {},
        step_results=step_results or {},
    )


class TestInputResolution:
    """Tests for $input.* variable resolution."""

    def test_simple_input_path(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"topic": "AI"})

        result = resolver.resolve("$input.topic", ctx)

        assert result == "AI"

    def test_nested_input_path(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"user": {"name": "Alice"}})

        result = resolver.resolve("$input.user.name", ctx)

        assert result == "Alice"

    def test_input_returns_dict(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"user": {"name": "Alice"}})

        result = resolver.resolve("$input.user", ctx)

        assert result == {"name": "Alice"}


class TestStepResultResolution:
    """Tests for $stepResult.* variable resolution."""

    def test_step_result_simple(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(step_results={"step1": {"output": "hello"}})

        result = resolver.resolve("$stepResult.step1.output", ctx)

        assert result == "hello"

    def test_step_result_nested(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(
            step_results={
                "classify": {"result": {"category": "technical"}},
            },
        )

        result = resolver.resolve("$stepResult.classify.result.category", ctx)

        assert result == "technical"


class TestEnvResolution:
    """Tests for $env.* variable resolution."""

    def test_env_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "sk-123")
        resolver = VariableResolver()
        ctx = _ctx()

        result = resolver.resolve("$env.API_KEY", ctx)

        assert result == "sk-123"

    def test_env_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISSING_VAR", raising=False)
        resolver = VariableResolver()
        ctx = _ctx()

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$env.MISSING_VAR", ctx)

        assert exc_info.value.code == "BEDDEL-RESOLVE-001"


class TestCustomNamespace:
    """Tests for custom namespace registration and resolution."""

    def test_register_and_resolve(self) -> None:
        resolver = VariableResolver()

        def secrets_handler(path: str, context: ExecutionContext) -> Any:
            return "super-secret-value"

        resolver.register_namespace("secrets", secrets_handler)
        ctx = _ctx()

        result = resolver.resolve("$secrets.api_key", ctx)

        assert result == "super-secret-value"

    def test_invalid_namespace_name_raises(self) -> None:
        resolver = VariableResolver()

        with pytest.raises(ValueError, match="Invalid namespace name"):
            resolver.register_namespace("", lambda p, c: None)


class TestRecursiveResolution:
    """Tests for recursive variable resolution."""

    def test_single_level_recursion(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"ref": "$input.value", "value": "final"})

        result = resolver.resolve("$input.ref", ctx)

        assert result == "final"

    def test_multi_level_recursion(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(
            inputs={
                "a": "$input.b",
                "b": "$input.c",
                "c": "done",
            },
        )

        result = resolver.resolve("$input.a", ctx)

        assert result == "done"


class TestCircularDetection:
    """Tests for circular reference detection (BEDDEL-RESOLVE-002)."""

    def test_circular_two_refs(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"a": "$input.b", "b": "$input.a"})

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$input.a", ctx)

        assert exc_info.value.code == "BEDDEL-RESOLVE-002"

    def test_circular_error_includes_chain(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"a": "$input.b", "b": "$input.a"})

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$input.a", ctx)

        chain = exc_info.value.details["chain"]
        assert "$input.a" in chain
        assert "$input.b" in chain


class TestMaxDepthExceeded:
    """Tests for max recursion depth exceeded (BEDDEL-RESOLVE-003)."""

    def test_max_depth_default(self) -> None:
        resolver = VariableResolver()
        # Build a chain of 12 refs: key0 -> key1 -> ... -> key11 -> key0
        inputs: dict[str, str] = {}
        for i in range(12):
            inputs[f"key{i}"] = f"$input.key{(i + 1) % 12}"
        ctx = _ctx(inputs=inputs)

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$input.key0", ctx)

        assert exc_info.value.code in ("BEDDEL-RESOLVE-002", "BEDDEL-RESOLVE-003")

    def test_max_depth_custom(self) -> None:
        resolver = VariableResolver(max_depth=2)
        ctx = _ctx(
            inputs={
                "a": "$input.b",
                "b": "$input.c",
                "c": "$input.d",
                "d": "end",
            },
        )

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$input.a", ctx)

        assert exc_info.value.code == "BEDDEL-RESOLVE-003"

    def test_max_depth_error_details(self) -> None:
        resolver = VariableResolver(max_depth=2)
        ctx = _ctx(
            inputs={
                "a": "$input.b",
                "b": "$input.c",
                "c": "$input.d",
                "d": "end",
            },
        )

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$input.a", ctx)

        assert exc_info.value.details["max_depth"] == 2


class TestUnresolvableVariable:
    """Tests for unresolvable variable errors (BEDDEL-RESOLVE-001)."""

    def test_missing_input_key(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx()

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$input.nonexistent", ctx)

        assert exc_info.value.code == "BEDDEL-RESOLVE-001"

    def test_error_includes_variable_path(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx()

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$input.nonexistent", ctx)

        assert exc_info.value.details["variable"] == "$input.nonexistent"

    def test_error_includes_namespace_and_path(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx()

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$input.nonexistent", ctx)

        details = exc_info.value.details
        assert "variable" in details
        assert "namespace" in details
        assert "path" in details

    def test_unknown_namespace(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx()

        with pytest.raises(ResolveError) as exc_info:
            resolver.resolve("$unknown.key", ctx)

        assert exc_info.value.code == "BEDDEL-RESOLVE-001"
        assert "unknown" in exc_info.value.message.lower()


class TestDictAndListResolution:
    """Tests for recursive resolution into dicts and lists."""

    def test_dict_resolution(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"topic": "AI"})

        result = resolver.resolve({"prompt": "$input.topic", "model": "gpt-4"}, ctx)

        assert result == {"prompt": "AI", "model": "gpt-4"}

    def test_list_resolution(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"a": "x", "b": "y"})

        result = resolver.resolve(["$input.a", "$input.b"], ctx)

        assert result == ["x", "y"]

    def test_nested_dict_in_list(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"name": "Alice", "age": 30})

        result = resolver.resolve(
            [{"user": "$input.name"}, "$input.age"],
            ctx,
        )

        assert result == [{"user": "Alice"}, 30]


class TestNonVariableStrings:
    """Tests for non-variable values passed through unchanged."""

    def test_plain_string_unchanged(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx()

        result = resolver.resolve("hello world", ctx)

        assert result == "hello world"

    def test_number_passthrough(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx()

        result = resolver.resolve(42, ctx)

        assert result == 42

    def test_boolean_passthrough(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx()

        result = resolver.resolve(True, ctx)

        assert result is True

    def test_none_passthrough(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx()

        result = resolver.resolve(None, ctx)

        assert result is None


class TestEmbeddedReferences:
    """Tests for inline variable references within larger strings."""

    def test_embedded_single_ref(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"name": "Alice"})

        result = resolver.resolve("Hello $input.name, welcome", ctx)

        assert result == "Hello Alice, welcome"

    def test_embedded_multiple_refs(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"greeting": "Hi", "name": "Alice"})

        result = resolver.resolve("$input.greeting $input.name", ctx)

        assert result == "Hi Alice"

    def test_embedded_with_non_string_value(self) -> None:
        resolver = VariableResolver()
        ctx = _ctx(inputs={"count": 42})

        result = resolver.resolve("Items: $input.count total", ctx)

        assert result == "Items: 42 total"
